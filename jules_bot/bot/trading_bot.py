import time
import uuid
import json
import os
from jules_bot.utils.logger import logger
from jules_bot.utils.config_manager import config_manager
from jules_bot.bot.account_manager import AccountManager
from jules_bot.core_logic.state_manager import StateManager
from jules_bot.core_logic.trader import Trader
from jules_bot.core_logic.strategy_rules import StrategyRules
from jules_bot.core.market_data_provider import MarketDataProvider
from jules_bot.database.postgres_manager import PostgresManager
from jules_bot.research.live_feature_calculator import LiveFeatureCalculator

class TradingBot:
    """
    The maestro that orchestrates all the components of the bot.
    """

    def __init__(self, mode: str, bot_id: str, market_data_provider: MarketDataProvider, db_manager: PostgresManager):
        self.mode = mode
        self.run_id = bot_id
        self.is_running = True
        self.market_data_provider = market_data_provider
        self.db_manager = db_manager
        self.symbol = config_manager.get('APP', 'symbol')
        self.state_file_path = "/tmp/bot_state.json"

    def _write_state_to_file(self, open_positions: list, current_price: float, wallet_balances: list, trade_history: list):
        """Saves the current bot state to a JSON file for the UI to read."""
        # Convert SQLAlchemy objects to dictionaries for JSON serialization
        serializable_trade_history = [t.to_dict() for t in trade_history]
        serializable_open_positions = [p.to_dict() for p in open_positions]

        state = {
            "mode": self.mode,
            "run_id": self.run_id,
            "symbol": self.symbol,
            "timestamp": time.time(),
            "current_price": str(current_price),
            "open_positions": serializable_open_positions,
            "wallet_balances": wallet_balances,
            "trade_history": serializable_trade_history
        }
        try:
            # Use atomic write to prevent partial reads from the UI
            temp_path = self.state_file_path + ".tmp"
            with open(temp_path, "w") as f:
                json.dump(state, f, indent=4)
            os.rename(temp_path, self.state_file_path)
        except (IOError, OSError) as e:
            logger.error(f"Could not write to state file {self.state_file_path}: {e}")

    def _handle_ui_commands(self, trader, state_manager, strategy_rules):
        """Checks for and processes command files from the UI."""
        command_dir = "commands"
        if not os.path.exists(command_dir):
            return

        for filename in os.listdir(command_dir):
            if filename.endswith(".json"):
                filepath = os.path.join(command_dir, filename)
                try:
                    with open(filepath, "r") as f:
                        command = json.load(f)

                    cmd_type = command.get("type")
                    logger.info(f"Processing UI command: {command}")

                    if cmd_type == "force_buy":
                        amount_usd = command.get("amount_usd")
                        if amount_usd:
                            success, buy_result = trader.execute_buy(amount_usd, self.run_id, {"reason": "manual_override"})
                            if success:
                                logger.info("Force buy successful. Calculating sell target and creating new position.")
                                purchase_price = float(buy_result.get('price'))
                                sell_target_price = strategy_rules.calculate_sell_target_price(purchase_price)
                                state_manager.create_new_position(buy_result, sell_target_price)
                            else:
                                logger.error(f"Force buy of {amount_usd} USD failed to execute.")

                    elif cmd_type == "force_sell":
                        trade_id = command.get("trade_id")
                        percentage = command.get("percentage", 100.0) # Default to 100%
                        if trade_id:
                            open_positions = state_manager.get_open_positions()
                            position_to_sell = next((p for p in open_positions if p.trade_id == trade_id), None)
                            if position_to_sell:
                                sell_fraction = float(percentage) / 100.0
                                original_quantity = float(position_to_sell.quantity or 0)
                                quantity_to_sell = original_quantity * sell_fraction

                                logger.info(f"Executing force sell for {percentage}% of trade {trade_id} ({quantity_to_sell:.8f} units).")

                                # Convert the Trade object to a dict for selling
                                sell_position_data = position_to_sell.to_dict()
                                sell_position_data['quantity'] = quantity_to_sell
                                trader.execute_sell(sell_position_data, self.run_id, {"reason": f"manual_override_{percentage}%_sell"})
                            else:
                                logger.warning(f"Could not find open position with trade_id: {trade_id} for force_sell.")

                    os.remove(filepath) # Remove command file after processing

                except Exception as e:
                    logger.error(f"Error processing command file {filename}: {e}", exc_info=True)
                    # Optionally, move to an 'error' directory instead of deleting
                    # os.rename(filepath, os.path.join(command_dir, "error", filename))


    def run(self):
        """
        The main loop for LIVE and PAPER TRADING.
        """
        if self.mode not in ['trade', 'test']:
            logger.error(f"The 'run' method cannot be called in '{self.mode}' mode.")
            return

        # Instantiate core components
        feature_calculator = LiveFeatureCalculator(self.db_manager, mode=self.mode)
        state_manager = StateManager(mode=self.mode, bot_id=self.run_id, db_manager=self.db_manager)
        trader = Trader(mode=self.mode)
        account_manager = AccountManager(trader.client)
        strategy_rules = StrategyRules(config_manager)

        # --- SYNC TRADES ON STARTUP ---
        if trader.is_ready:
            logger.info("Performing initial holdings synchronization...")
            state_manager.sync_holdings_with_binance(account_manager, strategy_rules, trader)

        if not trader.is_ready:
            logger.critical("Trader could not be initialized. Shutting down bot.")
            return

        self.is_running = True
        logger.info(f"🚀 --- TRADING BOT STARTED --- RUN ID: {self.run_id} --- SYMBOL: {self.symbol} --- MODE: {self.mode.upper()} --- 🚀")

        # Determine the base asset once (e.g., BTC from BTCUSDT)
        quote_asset = "USDT"
        base_asset = self.symbol.replace(quote_asset, "") if self.symbol.endswith(quote_asset) else self.symbol[:3]


        while self.is_running:
            try:
                logger.info("--- Starting new trading cycle ---")

                # 0. Check for and handle any UI commands
                self._handle_ui_commands(trader, state_manager, strategy_rules)

                # 1. Get the latest market data with all features
                final_candle = feature_calculator.get_current_candle_with_features()
                if final_candle.empty:
                    logger.warning("Could not generate final candle with features. Skipping cycle.")
                    time.sleep(10)
                    continue

                current_price = final_candle['close']
                decision_context = final_candle.to_dict()

                # 2. Check for potential sales
                open_positions = state_manager.get_open_positions()
                logger.info(f"Found {len(open_positions)} open position(s).")

                # Fetch all wallet balances
                all_prices = trader.get_all_prices()
                wallet_balances = account_manager.get_all_account_balances(all_prices)
                trade_history = state_manager.get_trade_history(mode=self.mode)

                # Update UI state file
                self._write_state_to_file(open_positions, float(current_price), wallet_balances, trade_history)

                # --- Refactored Sell Logic ---

                # 1. Identify all positions that meet the sell criteria
                positions_to_sell = [
                    p for p in open_positions
                    if float(current_price) >= (p.sell_target_price or float('inf'))
                ]

                if positions_to_sell:
                    logger.info(f"Found {len(positions_to_sell)} positions meeting sell criteria.")

                    # 2. Calculate the total quantity required for all sales
                    total_sell_quantity = sum(
                        float(p.quantity or 0) * strategy_rules.sell_factor for p in positions_to_sell
                    )

                    # 3. Fetch available balance ONCE
                    available_balance = trader.get_account_balance(asset=base_asset)

                    # 4. Perform a single, consolidated balance check
                    if total_sell_quantity > available_balance:
                        logger.warning(
                            f"INSUFFICIENT BALANCE: Attempting to sell a total of {total_sell_quantity:.8f} {base_asset}, "
                            f"but only {available_balance:.8f} is available. "
                            f"Skipping all sales for this cycle."
                        )
                    else:
                        logger.info(
                            f"Balance check passed. Available: {available_balance:.8f} {base_asset}, "
                            f"Required: {total_sell_quantity:.8f} {base_asset}. Proceeding with sales."
                        )
                        # 5. Execute sales if balance is sufficient
                        for position in positions_to_sell:
                            trade_id = position.trade_id
                            original_quantity = float(position.quantity or 0)
                            sell_quantity = original_quantity * strategy_rules.sell_factor
                            hodl_asset_amount = original_quantity - sell_quantity

                            sell_position_data = position.to_dict()
                            sell_position_data['quantity'] = sell_quantity

                            success, sell_result = trader.execute_sell(sell_position_data, self.run_id, decision_context)

                            if success:
                                buy_price = float(position.price or 0)
                                sell_price = float(sell_result.get('price'))

                                # Refactored PnL calculation
                                realized_pnl_usd = strategy_rules.calculate_realized_pnl(
                                    buy_price=buy_price,
                                    sell_price=sell_price,
                                    quantity_sold=sell_quantity
                                )
                                
                                hodl_asset_value_at_sell = hodl_asset_amount * current_price
                                commission_usd = float(sell_result.get('commission', 0))

                                sell_result.update({
                                    "commission_usd": commission_usd,
                                    "realized_pnl_usd": realized_pnl_usd,
                                    "hodl_asset_amount": hodl_asset_amount,
                                    "hodl_asset_value_at_sell": hodl_asset_value_at_sell
                                })

                                logger.info(f"Sell successful for {trade_id}. Recording partial sell and updating position.")
                                state_manager.record_partial_sell(
                                    original_trade_id=trade_id,
                                    remaining_quantity=hodl_asset_amount,
                                    sell_data=sell_result
                                )
                            else:
                                logger.error(f"Sell execution failed for position {trade_id}.")

                # 3. Check for a potential buy (New "Adaptive Momentum Grid" Strategy)
                open_positions_count = state_manager.get_open_positions_count()
                max_open_positions = int(config_manager.get('STRATEGY_RULES', 'max_open_positions', fallback=20))

                if open_positions_count < max_open_positions:
                    market_data = final_candle.to_dict()
                    should_buy, regime, reason = strategy_rules.evaluate_buy_signal(
                        market_data,
                        open_positions_count=open_positions_count
                    )

                    if should_buy:
                        logger.info(f"Buy signal triggered. Reason: {reason}. Evaluating capital.")
                        available_balance = trader.get_account_balance()

                        if available_balance <= 0:
                            logger.warning("Available balance is zero or less. Cannot execute buy.")
                        else:
                            buy_amount_usdt = strategy_rules.get_next_buy_amount(available_balance)
                            min_trade_size = float(config_manager.get('TRADING_STRATEGY', 'min_trade_size_usdt', fallback=10.0))

                            if buy_amount_usdt > min_trade_size:
                                logger.info(f"Executing buy for ${buy_amount_usdt:.2f} USD.")

                                # Enhanced data logging
                                decision_context = {
                                    "market_regime": regime,
                                    "buy_trigger_reason": reason,
                                    "ema_100_value": market_data.get('ema_100'),
                                    "ema_20_value": market_data.get('ema_20'),
                                    "lower_bollinger_band": market_data.get('bbl_20_2_0'),
                                    "regime_strength": None # Placeholder
                                }

                                success, buy_result = trader.execute_buy(buy_amount_usdt, self.run_id, decision_context)
                                if success:
                                    logger.info("Buy successful. Calculating sell target and creating new position.")
                                    purchase_price = float(buy_result.get('price'))
                                    sell_target_price = strategy_rules.calculate_sell_target_price(purchase_price)
                                    state_manager.create_new_position(buy_result, sell_target_price)
                            else:
                                logger.warning(f"Calculated buy amount (${buy_amount_usdt:.2f}) is below the minimum threshold of ${min_trade_size}. Skipping buy.")
                else:
                    logger.info(f"Maximum open positions ({max_open_positions}) reached. No new buys will be considered.")

                logger.info("--- Cycle complete. Waiting 60 seconds... ---")
                time.sleep(60)

            except KeyboardInterrupt:
                logger.info("\n[SHUTDOWN] Ctrl+C detected. Stopping main loop...")
                self.is_running = False
            except Exception as e:
                logger.critical(f"❌ A critical error occurred in the main loop: {e}", exc_info=True)
                time.sleep(300)

    def shutdown(self):
        """Handles all cleanup operations to ensure a clean exit."""
        logger.info("[SHUTDOWN] Initiating graceful shutdown procedure...")
        # In a real application, you would close connections and other resources here
        logger.info("[SHUTDOWN] Cleanup complete. Goodbye!")
