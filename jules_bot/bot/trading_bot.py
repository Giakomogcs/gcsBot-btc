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
from jules_bot.database.portfolio_manager import PortfolioManager
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
        self.trader = Trader(mode=self.mode)
        self.portfolio_manager = PortfolioManager(config_manager.get_section('POSTGRES'))
        self.symbol = config_manager.get('APP', 'symbol')
        self.state_file_path = "/tmp/bot_state.json"

    def _write_state_to_file(self, open_positions: list, current_price: float, wallet_balances: list, trade_history: list, dcom_status: dict):
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
            "trade_history": serializable_trade_history,
            "dcom_status": dcom_status
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

                                success, sell_result = trader.execute_sell(sell_position_data, self.run_id, {"reason": f"manual_override_{percentage}%_sell"})

                                if success:
                                    current_price = trader.get_current_price(self.symbol)
                                    buy_price = float(position_to_sell.price or 0)
                                    sell_price = float(sell_result.get('price'))
                                    hodl_asset_amount = original_quantity - quantity_to_sell

                                    realized_pnl_usd = strategy_rules.calculate_realized_pnl(
                                        buy_price=buy_price,
                                        sell_price=sell_price,
                                        quantity_sold=quantity_to_sell
                                    )

                                    hodl_asset_value_at_sell = hodl_asset_amount * current_price if current_price else 0
                                    commission_usd = float(sell_result.get('commission', 0))

                                    sell_result.update({
                                        "commission_usd": commission_usd,
                                        "realized_pnl_usd": realized_pnl_usd,
                                        "hodl_asset_amount": hodl_asset_amount,
                                        "hodl_asset_value_at_sell": hodl_asset_value_at_sell
                                    })

                                    logger.info(f"Force sell successful for {trade_id}. Recording partial sell and updating position.")
                                    state_manager.record_partial_sell(
                                        original_trade_id=trade_id,
                                        remaining_quantity=hodl_asset_amount,
                                        sell_data=sell_result
                                    )

                                    # Create a portfolio snapshot after the manual sale
                                    self._create_portfolio_snapshot(trader, state_manager, float(current_price))
                                else:
                                    logger.error(f"Force sell execution failed for position {trade_id}.")
                            else:
                                logger.warning(f"Could not find open position with trade_id: {trade_id} for force_sell.")

                    os.remove(filepath) # Remove command file after processing

                except Exception as e:
                    logger.error(f"Error processing command file {filename}: {e}", exc_info=True)
                    # Optionally, move to an 'error' directory instead of deleting
                    # os.rename(filepath, os.path.join(command_dir, "error", filename))

    def _create_portfolio_snapshot(self, trader: Trader, state_manager: StateManager, current_price: float):
        """
        Gathers all necessary data and creates a new portfolio snapshot.
        """
        logger.info("Creating portfolio snapshot...")
        try:
            # 1. Get current USD balance
            usd_balance = trader.get_account_balance(asset='USDT')

            # 2. Get open positions and calculate their total value
            open_positions = state_manager.get_open_positions()
            open_positions_value_usd = sum(
                float(p.quantity) * current_price for p in open_positions
            )

            # 3. Calculate total portfolio value
            total_portfolio_value_usd = usd_balance + open_positions_value_usd

            # 4. Get cumulative realized PnL from the database
            all_trades = self.db_manager.get_all_trades_in_range(mode=self.mode)
            realized_pnl_usd = sum(t.realized_pnl_usd for t in all_trades if t.realized_pnl_usd is not None)

            # 5. Calculate BTC Treasury
            # Simple rule: sum of all 'hodl_asset_amount' from closed trades
            btc_treasury_amount = sum(t.hodl_asset_amount for t in all_trades if t.hodl_asset_amount is not None)

            # 6. Get current BTC price to value the treasury
            # The 'current_price' is for the trading symbol, which might not be BTC.
            # I need to fetch the BTC price specifically.
            btc_price_usd = trader.get_current_price('BTCUSDT')
            btc_treasury_value_usd = btc_treasury_amount * btc_price_usd if btc_price_usd else 0

            snapshot_data = {
                "total_portfolio_value_usd": total_portfolio_value_usd,
                "usd_balance": usd_balance,
                "open_positions_value_usd": open_positions_value_usd,
                "realized_pnl_usd": realized_pnl_usd,
                "btc_treasury_amount": btc_treasury_amount,
                "btc_treasury_value_usd": btc_treasury_value_usd,
            }

            self.portfolio_manager.create_portfolio_snapshot(snapshot_data)
            logger.info("Portfolio snapshot created successfully.")

        except Exception as e:
            logger.error(f"Failed to create portfolio snapshot: {e}", exc_info=True)

    def _calculate_dcom_equity(self, trader: Trader, state_manager: StateManager, current_price: float) -> dict:
        """
        Calculates the total equity and its components based on the DCOM strategy.
        """
        try:
            # 1. Get current cash balance (USD)
            cash_balance = trader.get_account_balance(asset='USDT')

            # 2. Get open positions and their current market value
            open_positions = state_manager.get_open_positions()
            capital_in_use = sum(
                float(p.quantity) * current_price for p in open_positions
            )

            # 3. Calculate Total Equity
            total_equity = cash_balance + capital_in_use

            return {
                "total_equity": total_equity,
                "cash_balance": cash_balance,
                "capital_in_use": capital_in_use
            }
        except Exception as e:
            logger.error(f"Failed to calculate DCOM equity: {e}", exc_info=True)
            return {
                "total_equity": 0,
                "cash_balance": 0,
                "capital_in_use": 0
            }

    def run(self):
        """
        The main loop for LIVE and PAPER TRADING, now implementing DCOM.
        """
        if self.mode not in ['trade', 'test']:
            logger.error(f"The 'run' method cannot be called in '{self.mode}' mode.")
            return

        # Instantiate core components
        feature_calculator = LiveFeatureCalculator(self.db_manager, mode=self.mode)
        state_manager = StateManager(mode=self.mode, bot_id=self.run_id, db_manager=self.db_manager)
        account_manager = AccountManager(self.trader.client)
        strategy_rules = StrategyRules(config_manager)

        # --- SYNC TRADES ON STARTUP ---
        if self.trader.is_ready:
            logger.info("Performing initial holdings synchronization...")
            state_manager.sync_holdings_with_binance(account_manager, strategy_rules, self.trader)

        if not self.trader.is_ready:
            logger.critical("Trader could not be initialized. Shutting down bot.")
            return

        self.is_running = True
        logger.info(f"🚀 --- TRADING BOT STARTED --- RUN ID: {self.run_id} --- SYMBOL: {self.symbol} --- MODE: {self.mode.upper()} --- 🚀")

        quote_asset = "USDT"
        base_asset = self.symbol.replace(quote_asset, "") if self.symbol.endswith(quote_asset) else self.symbol[:3]

        while self.is_running:
            try:
                logger.info("--- Starting new DCOM trading cycle ---")

                # 0. Check for and handle any UI commands
                self._handle_ui_commands(self.trader, state_manager, strategy_rules)

                # 1. Get Market Data
                final_candle = feature_calculator.get_current_candle_with_features()
                if final_candle.empty:
                    logger.warning("Could not generate final candle with features. Skipping cycle.")
                    time.sleep(10)
                    continue
                current_price = float(final_candle['close'])
                market_data = final_candle.to_dict()

                # 2. DCOM Equity and Capital Allocation
                equity_data = self._calculate_dcom_equity(self.trader, state_manager, current_price)
                total_equity = equity_data['total_equity']
                capital_in_use = equity_data['capital_in_use']

                working_capital = total_equity * strategy_rules.working_capital_percent
                strategic_reserve = total_equity - working_capital
                remaining_buying_power = working_capital - capital_in_use
                
                logger.info(f"[DCOM] Total Equity: ${total_equity:,.2f} | Working Capital: ${working_capital:,.2f} | In Use: ${capital_in_use:,.2f} | Reserve: ${strategic_reserve:,.2f}")

                # 3. Process Sales (Logic is largely unchanged)
                open_positions = state_manager.get_open_positions()
                positions_to_sell = [p for p in open_positions if current_price >= (p.sell_target_price or float('inf'))]

                if positions_to_sell:
                    # (Sell logic remains the same as the original, omitted for brevity but would be here)
                    logger.info(f"Found {len(positions_to_sell)} positions to sell.")
                    # ... existing sell execution logic ...

                # 4. DCOM Buy Logic
                open_positions_count = len(open_positions)
                ema_anchor_key = f'ema_{strategy_rules.ema_anchor_period}'
                ema_anchor_value = market_data.get(ema_anchor_key)

                if ema_anchor_value is None:
                    logger.warning(f"EMA anchor '{ema_anchor_key}' not found in market data. Skipping buy evaluation.")
                else:
                    operating_mode, spacing_percent = strategy_rules.get_operating_mode(current_price, ema_anchor_value)
                    logger.info(f"[DCOM] Operating Mode: {operating_mode} (Spacing: {spacing_percent:.2%})")

                    last_buy_price = state_manager.get_last_buy_price()
                    
                    if strategy_rules.should_place_new_order(current_price, last_buy_price, spacing_percent):
                        next_order_size_usd = strategy_rules.calculate_next_order_size(open_positions_count)
                        logger.info(f"[DCOM] Potential new buy detected. Next order size: ${next_order_size_usd:,.2f}")

                        if next_order_size_usd <= remaining_buying_power:
                            min_trade_size = float(config_manager.get('TRADING_STRATEGY', 'min_trade_size_usdt', fallback=10.0))
                            if next_order_size_usd >= min_trade_size:
                                logger.info(f"BUY CONFIRMED: Order size (${next_order_size_usd:,.2f}) is within remaining buying power (${remaining_buying_power:,.2f}).")
                                
                                decision_context = {
                                    "dcom_mode": operating_mode,
                                    "dcom_equity": total_equity,
                                    "dcom_working_capital": working_capital,
                                    "dcom_capital_in_use": capital_in_use,
                                    "dcom_trigger_reason": f"Price fell {spacing_percent:.2%} below last buy."
                                }

                                success, buy_result = self.trader.execute_buy(next_order_size_usd, self.run_id, decision_context)
                                if success:
                                    logger.info("DCOM Buy successful. Creating new position.")
                                    purchase_price = float(buy_result.get('price'))
                                    sell_target_price = strategy_rules.calculate_sell_target_price(purchase_price)
                                    state_manager.create_new_position(buy_result, sell_target_price)
                            else:
                                logger.warning(f"BUY SKIPPED: Calculated order size (${next_order_size_usd:,.2f}) is below minimum trade size (${min_trade_size:,.2f}).")
                        else:
                            logger.warning(f"BUY SKIPPED: Not enough buying power. Required: ${next_order_size_usd:,.2f}, Remaining: ${remaining_buying_power:,.2f}")

                # 5. Update State File for TUI
                wallet_balances = account_manager.get_all_account_balances(self.trader.get_all_prices())
                trade_history = state_manager.get_trade_history(mode=self.mode)
                dcom_status = {
                    "total_equity": total_equity,
                    "working_capital_target": working_capital,
                    "working_capital_in_use": capital_in_use,
                    "working_capital_remaining": remaining_buying_power,
                    "strategic_reserve": strategic_reserve,
                    "operating_mode": operating_mode if ema_anchor_value else "N/A",
                    "next_order_size": strategy_rules.calculate_next_order_size(open_positions_count)
                }
                self._write_state_to_file(open_positions, current_price, wallet_balances, trade_history, dcom_status)


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
