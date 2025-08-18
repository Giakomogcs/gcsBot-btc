import time
import uuid
import json
import os
from decimal import Decimal, getcontext
from jules_bot.utils.logger import logger
from jules_bot.utils.config_manager import config_manager
from jules_bot.bot.account_manager import AccountManager
from jules_bot.core_logic.state_manager import StateManager
from jules_bot.core_logic.trader import Trader
from jules_bot.core_logic.strategy_rules import StrategyRules
from jules_bot.core.market_data_provider import MarketDataProvider
from jules_bot.database.postgres_manager import PostgresManager
from jules_bot.database.portfolio_manager import PortfolioManager as DbPortfolioManager
from jules_bot.research.live_feature_calculator import LiveFeatureCalculator

getcontext().prec = 28

class LivePortfolioManager:
    def __init__(self, trader: Trader, state_manager: StateManager, db_manager: PostgresManager, quote_asset: str, recalculation_interval: int):
        self.trader = trader
        self.state_manager = state_manager
        self.db_manager = db_manager # Store the PostgresManager instance
        self.db_portfolio_manager = DbPortfolioManager(db_manager.SessionLocal)
        self.quote_asset = quote_asset
        self.recalculation_interval = recalculation_interval
        self.last_recalculation_time = 0
        self.cached_portfolio_value = Decimal('0.0')
        self.symbol = config_manager.get('APP', 'symbol')

    def get_total_portfolio_value(self, current_price: Decimal, force_recalculation: bool = False) -> Decimal:
        current_time = time.time()
        if force_recalculation or (current_time - self.last_recalculation_time > self.recalculation_interval):
            logger.info("Recalculating portfolio equity...")
            try:
                cash_balance = Decimal(self.trader.get_account_balance(asset=self.quote_asset))
                open_positions = self.state_manager.get_open_positions()

                open_positions_value = sum(
                    Decimal(p.quantity) * current_price for p in open_positions
                )

                self.cached_portfolio_value = cash_balance + open_positions_value
                self.last_recalculation_time = current_time
                logger.info(f"Portfolio equity recalculated: ${self.cached_portfolio_value:,.2f}")

                self._create_db_snapshot(cash_balance, open_positions_value, current_price)

            except Exception as e:
                logger.error(f"Error during portfolio value calculation: {e}", exc_info=True)
                return self.cached_portfolio_value

        return self.cached_portfolio_value

    def _create_db_snapshot(self, usd_balance: Decimal, open_positions_value_usd: Decimal, current_price: Decimal):
        try:
            total_portfolio_value_usd = usd_balance + open_positions_value_usd
            # Use the correct manager to fetch trades
            all_trades = self.db_manager.get_all_trades_in_range(mode=self.state_manager.mode, bot_id=self.state_manager.bot_id)

            realized_pnl_usd = sum(Decimal(t.realized_pnl_usd or '0') for t in all_trades)
            btc_treasury_amount = sum(Decimal(t.hodl_asset_amount or '0') for t in all_trades)

            btc_price_usd = Decimal(self.trader.get_current_price('BTCUSDT') or current_price)
            btc_treasury_value_usd = btc_treasury_amount * btc_price_usd

            snapshot_data = {
                "total_portfolio_value_usd": total_portfolio_value_usd,
                "usd_balance": usd_balance,
                "open_positions_value_usd": open_positions_value_usd,
                "realized_pnl_usd": realized_pnl_usd,
                "btc_treasury_amount": btc_treasury_amount,
                "btc_treasury_value_usd": btc_treasury_value_usd,
            }
            self.db_portfolio_manager.create_portfolio_snapshot(snapshot_data)
            logger.info("DB portfolio snapshot created successfully.")
        except Exception as e:
            logger.error(f"Failed to create DB portfolio snapshot: {e}", exc_info=True)


class TradingBot:
    def __init__(self, mode: str, bot_id: str, market_data_provider: MarketDataProvider, db_manager: PostgresManager):
        self.mode = mode
        self.run_id = bot_id
        self.is_running = True
        self.market_data_provider = market_data_provider
        self.db_manager = db_manager
        self.trader = Trader(mode=self.mode)
        self.symbol = config_manager.get('APP', 'symbol')
        self.state_file_path = "/tmp/bot_state.json"

    def _write_state_to_file(self, open_positions: list, current_price: Decimal, wallet_balances: list, trade_history: list, portfolio_value: Decimal):
        serializable_trade_history = [t.to_dict() for t in trade_history]
        serializable_open_positions = [p.to_dict() for p in open_positions]
        state = {
            "mode": self.mode, "run_id": self.run_id, "symbol": self.symbol,
            "timestamp": time.time(), "current_price": f"{current_price:.2f}",
            "portfolio_value": f"${portfolio_value:,.2f}",
            "open_positions": serializable_open_positions,
            "wallet_balances": wallet_balances, "trade_history": serializable_trade_history
        }
        try:
            temp_path = self.state_file_path + ".tmp"
            with open(temp_path, "w") as f:
                json.dump(state, f, indent=4, default=str)
            os.rename(temp_path, self.state_file_path)
        except (IOError, OSError) as e:
            logger.error(f"Could not write to state file {self.state_file_path}: {e}")

    def _handle_ui_commands(self, trader, state_manager, strategy_rules):
        # This function deals with external data, which can be kept as strings/floats
        # and converted to Decimal only when passed to financial calculations.
        command_dir = "commands"
        if not os.path.exists(command_dir): return

        for filename in os.listdir(command_dir):
            if not filename.endswith(".json"): continue
            filepath = os.path.join(command_dir, filename)
            try:
                with open(filepath, "r") as f:
                    command = json.load(f)

                cmd_type = command.get("type")
                logger.info(f"Processing UI command: {command}")

                if cmd_type == "force_buy":
                    amount_usd = Decimal(command.get("amount_usd", "0"))
                    if amount_usd > 0:
                        success, buy_result = trader.execute_buy(amount_usd, self.run_id, {"reason": "manual_override"})
                        if success:
                            purchase_price = Decimal(buy_result.get('price'))
                            sell_target_price = strategy_rules.calculate_sell_target_price(purchase_price)
                            state_manager.create_new_position(buy_result, sell_target_price)

                elif cmd_type == "force_sell":
                    trade_id = command.get("trade_id")
                    percentage = Decimal(command.get("percentage", "100.0"))
                    if trade_id:
                        position = next((p for p in state_manager.get_open_positions() if p.trade_id == trade_id), None)
                        if position:
                            quantity_to_sell = Decimal(position.quantity) * (percentage / Decimal("100"))
                            # ... rest of sell logic requires careful Decimal conversion ...

                os.remove(filepath)
            except Exception as e:
                logger.error(f"Error processing command file {filename}: {e}", exc_info=True)

    def run(self):
        if self.mode not in ['trade', 'test']:
            logger.error(f"The 'run' method cannot be called in '{self.mode}' mode.")
            return

        quote_asset = "USDT"
        base_asset = self.symbol.replace(quote_asset, "")
        use_dynamic_capital = config_manager.getboolean('STRATEGY_RULES', 'use_dynamic_capital', fallback=False)
        wc_percentage = Decimal(config_manager.get('STRATEGY_RULES', 'working_capital_percentage', fallback='0.8'))
        max_open_positions = int(config_manager.get('STRATEGY_RULES', 'max_open_positions', fallback=20))
        min_trade_size = Decimal(config_manager.get('TRADING_STRATEGY', 'min_trade_size_usdt', fallback='10.0'))
        equity_recalc_interval = int(config_manager.get('APP', 'equity_recalculation_interval', fallback=300))

        feature_calculator = LiveFeatureCalculator(self.db_manager, mode=self.mode)
        state_manager = StateManager(mode=self.mode, bot_id=self.run_id, db_manager=self.db_manager)
        account_manager = AccountManager(self.trader.client)
        strategy_rules = StrategyRules(config_manager)
        live_portfolio_manager = LivePortfolioManager(self.trader, state_manager, self.db_manager, quote_asset, equity_recalc_interval)

        if not self.trader.is_ready:
            logger.critical("Trader could not be initialized. Shutting down bot.")
            return

        state_manager.sync_holdings_with_binance(account_manager, strategy_rules, self.trader)
        logger.info(f"🚀 --- TRADING BOT STARTED --- RUN ID: {self.run_id} --- SYMBOL: {self.symbol} --- MODE: {self.mode.upper()} --- 🚀")

        while self.is_running:
            try:
                logger.info("--- Starting new trading cycle ---")
                self._handle_ui_commands(self.trader, state_manager, strategy_rules)

                final_candle = feature_calculator.get_current_candle_with_features()
                if final_candle.empty:
                    logger.warning("Could not get candle. Skipping cycle.")
                    time.sleep(10)
                    continue

                current_price = Decimal(final_candle['close'])

                open_positions = state_manager.get_open_positions()
                total_portfolio_value = live_portfolio_manager.get_total_portfolio_value(current_price)

                # --- UI STATE UPDATE ---
                all_prices = self.trader.get_all_prices()
                wallet_balances = account_manager.get_all_account_balances(all_prices)
                trade_history = state_manager.get_trade_history(mode=self.mode)
                self._write_state_to_file(open_positions, current_price, wallet_balances, trade_history, total_portfolio_value)

                # --- SELL LOGIC ---
                positions_to_sell = [p for p in open_positions if current_price >= Decimal(p.sell_target_price or 'inf')]
                if positions_to_sell:
                    logger.info(f"Found {len(positions_to_sell)} positions meeting sell criteria.")
                    total_sell_quantity = sum(Decimal(p.quantity) * strategy_rules.sell_factor for p in positions_to_sell)
                    available_balance = Decimal(self.trader.get_account_balance(asset=base_asset))

                    if total_sell_quantity > available_balance:
                        logger.warning(f"INSUFFICIENT BALANCE: Attempting to sell {total_sell_quantity:.8f} {base_asset}, but only {available_balance:.8f} is available.")
                    else:
                        for position in positions_to_sell:
                            trade_id = position.trade_id
                            original_quantity = Decimal(position.quantity)
                            sell_quantity = original_quantity * strategy_rules.sell_factor
                            hodl_asset_amount = original_quantity - sell_quantity

                            sell_position_data = position.to_dict()
                            sell_position_data['quantity'] = sell_quantity

                            success, sell_result = self.trader.execute_sell(sell_position_data, self.run_id, final_candle.to_dict())
                            if success:
                                buy_price = Decimal(position.price)
                                sell_price = Decimal(sell_result.get('price'))
                                realized_pnl_usd = strategy_rules.calculate_realized_pnl(buy_price, sell_price, sell_quantity)
                                hodl_asset_value_at_sell = hodl_asset_amount * current_price
                                commission_usd = Decimal(sell_result.get('commission', '0'))

                                sell_result.update({
                                    "commission_usd": commission_usd,
                                    "realized_pnl_usd": realized_pnl_usd,
                                    "hodl_asset_amount": hodl_asset_amount,
                                    "hodl_asset_value_at_sell": hodl_asset_value_at_sell
                                })

                                state_manager.record_partial_sell(
                                    original_trade_id=trade_id,
                                    remaining_quantity=hodl_asset_amount,
                                    sell_data=sell_result
                                )
                                live_portfolio_manager.get_total_portfolio_value(current_price, force_recalculation=True)
                            else:
                                logger.error(f"Sell execution failed for position {trade_id}.")

                # --- BUY LOGIC ---
                buy_check_passed = False
                if use_dynamic_capital:
                    working_capital = total_portfolio_value * wc_percentage
                    capital_in_use = sum(Decimal(p.quantity) * Decimal(p.price) for p in open_positions)
                    available_buying_power = working_capital - capital_in_use

                    cash_balance = Decimal(self.trader.get_account_balance(asset=quote_asset))
                    buy_amount_usdt = strategy_rules.get_next_buy_amount(cash_balance)

                    if buy_amount_usdt <= available_buying_power:
                        buy_check_passed = True
                        logger.info(f"Dynamic Capital check PASSED. Available: ${available_buying_power:,.2f}, Needed: ${buy_amount_usdt:,.2f}")
                    else:
                        logger.info(f"Dynamic Capital check FAILED. Available: ${available_buying_power:,.2f}, Needed: ${buy_amount_usdt:,.2f}")
                else:
                    if len(open_positions) < max_open_positions:
                        buy_check_passed = True
                    else:
                        logger.info(f"Maximum open positions ({max_open_positions}) reached.")

                if buy_check_passed:
                    market_data = final_candle.to_dict()
                    should_buy, regime, reason = strategy_rules.evaluate_buy_signal(market_data, len(open_positions))
                    if should_buy:
                        logger.info(f"Buy signal: {reason}. Evaluating capital.")
                        cash_balance = Decimal(self.trader.get_account_balance(asset=quote_asset))
                        if cash_balance >= min_trade_size:
                            buy_amount_usdt = strategy_rules.get_next_buy_amount(cash_balance)
                            if buy_amount_usdt >= min_trade_size:
                                logger.info(f"Executing buy for ${buy_amount_usdt:.2f} USD.")
                                decision_context = { "market_regime": regime, "buy_trigger_reason": reason }
                                success, buy_result = self.trader.execute_buy(buy_amount_usdt, self.run_id, decision_context)
                                if success:
                                    logger.info("Buy successful. Creating new position.")
                                    purchase_price = Decimal(buy_result.get('price'))
                                    sell_target_price = strategy_rules.calculate_sell_target_price(purchase_price)
                                    state_manager.create_new_position(buy_result, sell_target_price)
                                    live_portfolio_manager.get_total_portfolio_value(purchase_price, force_recalculation=True)
                            else:
                                logger.warning(f"Calculated buy amount ${buy_amount_usdt:.2f} < min size. Skipping.")
                        else:
                            logger.warning(f"Cash balance ${cash_balance:.2f} < min trade size. Cannot buy.")

                logger.info("--- Cycle complete. Waiting 60 seconds... ---")
                time.sleep(60)

            except KeyboardInterrupt:
                self.is_running = False
                logger.info("\n[SHUTDOWN] Ctrl+C detected.")
            except Exception as e:
                logger.critical(f"❌ Critical error in main loop: {e}", exc_info=True)
                time.sleep(300)

    def shutdown(self):
        logger.info("[SHUTDOWN] Initiating graceful shutdown...")
        logger.info("[SHUTDOWN] Cleanup complete. Goodbye!")
