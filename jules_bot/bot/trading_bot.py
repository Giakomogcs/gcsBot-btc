import time
import uuid
import json
import os
from decimal import Decimal, getcontext, InvalidOperation
from jules_bot.utils.logger import logger
from jules_bot.utils.config_manager import config_manager
from jules_bot.bot.account_manager import AccountManager
from jules_bot.core_logic.state_manager import StateManager
from jules_bot.core_logic.trader import Trader
from jules_bot.core_logic.strategy_rules import StrategyRules
from jules_bot.core_logic.capital_manager import CapitalManager
from jules_bot.core_logic.dynamic_parameters import DynamicParameters
from jules_bot.bot.situational_awareness import SituationalAwareness
from jules_bot.core.market_data_provider import MarketDataProvider
from jules_bot.database.postgres_manager import PostgresManager
from jules_bot.database.portfolio_manager import PortfolioManager as DbPortfolioManager
from jules_bot.research.live_feature_calculator import LiveFeatureCalculator
from jules_bot.services.status_service import StatusService
from jules_bot.utils.helpers import _calculate_progress_pct

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
            # Use the correct manager to fetch trades for the specific bot run
            all_trades = self.db_manager.get_trades_by_run_id(run_id=self.state_manager.bot_id)

            realized_pnl_usd = sum(Decimal(str(t.realized_pnl_usd or '0')) for t in all_trades)
            btc_treasury_amount = sum(Decimal(str(t.hodl_asset_amount or '0')) for t in all_trades)

            # Ensure the price is fetched as a string to maintain precision with Decimal
            btc_price_str = self.trader.get_current_price('BTCUSDT')
            btc_price_usd = Decimal(btc_price_str) if btc_price_str else current_price
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
        # ConfigManager MUST be initialized before this class is instantiated.
        if not config_manager.bot_name:
            raise RuntimeError("ConfigManager must be initialized before creating a TradingBot.")

        self.mode = mode
        self.run_id = bot_id
        self.bot_name = config_manager.bot_name # Use the already-initialized bot name
        self.is_running = True
        self.market_data_provider = market_data_provider
        self.db_manager = db_manager

        # Trader will now correctly use the bot-specific config loaded by config_manager
        self.trader = Trader(mode=self.mode)
        self.symbol = config_manager.get('APP', 'symbol')
        self.state_file_path = f"/tmp/bot_state_{self.bot_name}.json"

        # -- State for Reversal Buy Strategy --
        self.is_monitoring_for_reversal = False
        self.lowest_price_since_monitoring_started = None
        self.monitoring_started_at = None

        # -- Load Core Strategy Configuration --
        self.min_trade_size = Decimal(config_manager.get('TRADING_STRATEGY', 'min_trade_size_usdt', fallback='10.0'))


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
        command_dir = os.path.join("commands", self.bot_name)
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
                        if amount_usd < self.min_trade_size:
                            logger.error(f"Manual buy command for ${amount_usd:.2f} is below the minimum trade size of ${self.min_trade_size:.2f}. Aborting.")
                        else:
                            success, buy_result = trader.execute_buy(amount_usd, self.run_id, {"reason": "manual_override"})
                            if success:
                                purchase_price = Decimal(buy_result.get('price'))
                                sell_target_price = strategy_rules.calculate_sell_target_price(purchase_price)
                                logger.info(f"Calculated sell target for manual buy. Purchase price: ${purchase_price:,.2f}, Target price: ${sell_target_price:,.2f}")
                                state_manager.create_new_position(buy_result, sell_target_price)
                            else:
                                logger.error(f"Manual buy for ${amount_usd:.2f} failed. See trader logs for details (e.g., insufficient funds).")

                elif cmd_type == "force_sell":
                    trade_id = command.get("trade_id")
                    percentage = Decimal(command.get("percentage", "100.0"))
                    if trade_id:
                        position = next((p for p in state_manager.get_open_positions() if p.trade_id == trade_id), None)
                        if position:
                            logger.info(f"Force selling {percentage}% of trade {trade_id}.")
                            # This is a simplified sell logic for manual override.
                            # A more robust implementation would check available balance.
                            quantity_to_sell = Decimal(position.quantity) * (percentage / Decimal("100"))

                            # Create mock sell_position_data
                            sell_position_data = position.to_dict()
                            sell_position_data['quantity'] = quantity_to_sell

                            success, sell_result = trader.execute_sell(sell_position_data, self.run_id, {"reason": "manual_force_sell"})
                            if success:
                                # Calculate PnL for the sold portion
                                buy_price = Decimal(str(position.price))
                                sell_price = Decimal(str(sell_result.get('price')))
                                realized_pnl = strategy_rules.calculate_realized_pnl(buy_price, sell_price, quantity_to_sell)

                                # Close the position correctly instead of just reconciling
                                state_manager.close_forced_position(trade_id, sell_result, realized_pnl)
                                logger.info(f"Successfully closed trade {trade_id} via force sell with PnL ${realized_pnl:.2f}.")
                            else:
                                logger.error(f"Manual sell for trade {trade_id} failed. See trader logs for details.")

                os.remove(filepath)
            except Exception as e:
                logger.error(f"Error processing command file {filename}: {e}", exc_info=True)

    def _calculate_buy_progress(self, market_data: dict, open_positions_count: int, current_params: dict) -> tuple[Decimal, Decimal]:
        """
        Calculates the target price for the next buy and the progress towards it.
        """
        try:
            current_price = Decimal(str(market_data.get('close')))
            high_price = Decimal(str(market_data.get('high', current_price)))
            buy_dip_percentage = current_params.get('buy_dip_percentage', Decimal('0.02'))

            # The buy target is a percentage dip from the recent high
            target_price = high_price * (Decimal('1') - buy_dip_percentage)

            # The "start price" for measuring progress is the recent high.
            progress = _calculate_progress_pct(current_price, high_price, target_price)

            return target_price, progress

        except (InvalidOperation, TypeError):
            return Decimal('0'), Decimal('0')

    def run(self):
        if self.mode not in ['trade', 'test']:
            logger.error(f"The 'run' method cannot be called in '{self.mode}' mode.")
            return

        quote_asset = "USDT"
        base_asset = self.symbol.replace(quote_asset, "")

        # --- Load Strategy Configuration ---
        equity_recalc_interval = int(config_manager.get('APP', 'equity_recalculation_interval', fallback=300))

        # Reversal strategy specific configs
        self.reversal_buy_threshold_percent = Decimal(config_manager.get('STRATEGY_RULES', 'reversal_buy_threshold_percent', fallback='0.005'))
        self.reversal_monitoring_timeout_seconds = int(config_manager.get('STRATEGY_RULES', 'reversal_monitoring_timeout_seconds', fallback='300'))

        feature_calculator = LiveFeatureCalculator(self.db_manager, mode=self.mode)
        status_service = StatusService(self.db_manager, config_manager, feature_calculator)
        state_manager = StateManager(mode=self.mode, bot_id=self.run_id, db_manager=self.db_manager, feature_calculator=feature_calculator)
        account_manager = AccountManager(self.trader.client)
        strategy_rules = StrategyRules(config_manager)
        capital_manager = CapitalManager(config_manager, strategy_rules)
        live_portfolio_manager = LivePortfolioManager(self.trader, state_manager, self.db_manager, quote_asset, equity_recalc_interval)

        # --- Dynamic Strategy Components ---
        dynamic_params = DynamicParameters(config_manager)
        sa_instance = SituationalAwareness()

        # The SituationalAwareness model is rule-based and doesn't require a separate training step.
        # Its transform method calculates regimes dynamically based on the data provided.
        logger.info("Situational Awareness model is rule-based and ready.")

        if not self.trader.is_ready:
            logger.critical("Trader could not be initialized. Shutting down bot.")
            return

        state_manager.sync_holdings_with_binance(account_manager, strategy_rules, self.trader)
        logger.info(f"🚀 --- TRADING BOT STARTED --- BOT NAME: {self.bot_name} --- RUN ID: {self.run_id} --- SYMBOL: {self.symbol} --- MODE: {self.mode.upper()} --- 🚀")

        while self.is_running:
            try:
                logger.info("--- Starting new trading cycle ---")
                state_manager.recalculate_open_position_targets(strategy_rules, sa_instance, dynamic_params)
                self._handle_ui_commands(self.trader, state_manager, strategy_rules)

                features_df = feature_calculator.get_features_dataframe()
                if features_df.empty:
                    logger.warning("Could not get features dataframe. Skipping cycle.")
                    time.sleep(10)
                    continue

                final_candle = features_df.iloc[-1]

                # Defensively check for NaN values in the latest candle data.
                # This can happen if there's not enough historical data for an indicator.
                if final_candle.isnull().any():
                    logger.warning(f"Final candle contains NaN values, skipping cycle. Data: {final_candle.to_dict()}")
                    time.sleep(10)
                    continue

                # --- DYNAMIC STRATEGY LOGIC ---
                current_regime = -1 # Default to fallback
                if sa_instance:
                    try:
                        # Pass the full dataframe to transform
                        regime_df = sa_instance.transform(features_df)
                        if not regime_df.empty:
                            # Get the regime from the last row
                            current_regime = int(regime_df['market_regime'].iloc[-1])
                            logger.info(f"Current market regime detected: {current_regime}")
                        else:
                            logger.warning("Could not determine market regime from candle.")
                    except Exception as e:
                        logger.error(f"Error getting market regime: {e}", exc_info=True)

                dynamic_params.update_parameters(current_regime)
                current_params = dynamic_params.parameters
                logger.info(f"Using strategy parameters for Regime {current_regime}: {current_params}")

                current_price = Decimal(final_candle['close'])
                open_positions = state_manager.get_open_positions()
                total_portfolio_value = live_portfolio_manager.get_total_portfolio_value(current_price)

                all_prices = self.trader.get_all_prices()
                wallet_balances = account_manager.get_all_account_balances(all_prices)

                # Fetch recent trades for difficulty calculation
                end_date = datetime.utcnow()
                start_date = end_date - timedelta(hours=capital_manager.difficulty_reset_timeout_hours)
                trade_history = self.db_manager.get_all_trades_in_range(
                    mode=self.mode,
                    start_date=start_date,
                    end_date=end_date
                )

                # For the state file, we might still want the full history
                full_trade_history = state_manager.get_trade_history_for_run()
                self._write_state_to_file(open_positions, current_price, wallet_balances, full_trade_history, total_portfolio_value)

                # --- SELL LOGIC ---
                positions_to_sell = [p for p in open_positions if current_price >= Decimal(str(p.sell_target_price or 'inf'))]
                if positions_to_sell:
                    logger.info(f"Found {len(positions_to_sell)} positions meeting sell criteria.")
                    # ... (rest of sell logic is unchanged)
                    total_sell_quantity = sum(Decimal(str(p.quantity)) * strategy_rules.sell_factor for p in positions_to_sell)
                    available_balance = Decimal(self.trader.get_account_balance(asset=base_asset))

                    if total_sell_quantity > available_balance:
                        logger.warning(f"INSUFFICIENT BALANCE: Bot state is out of sync. Attempting to sell {total_sell_quantity:.8f} {base_asset}, but only {available_balance:.8f} is available.")
                        logger.info("Triggering state reconciliation with exchange balance.")
                        state_manager.reconcile_holdings(self.symbol, self.trader)
                    else:
                        for position in positions_to_sell:
                            trade_id = position.trade_id
                            original_quantity = Decimal(str(position.quantity))
                            sell_quantity = original_quantity * strategy_rules.sell_factor
                            hodl_asset_amount = original_quantity - sell_quantity

                            sell_position_data = position.to_dict()
                            sell_position_data['quantity'] = sell_quantity

                            success, sell_result = self.trader.execute_sell(sell_position_data, self.run_id, final_candle.to_dict())
                            if success:
                                buy_price = Decimal(str(position.price))
                                sell_price = Decimal(str(sell_result.get('price')))
                                realized_pnl_usd = strategy_rules.calculate_realized_pnl(buy_price, sell_price, sell_quantity)
                                hodl_asset_value_at_sell = hodl_asset_amount * current_price
                                commission_usd = Decimal(str(sell_result.get('commission', '0')))
                                sell_result.update({
                                    "commission_usd": commission_usd, "realized_pnl_usd": realized_pnl_usd,
                                    "hodl_asset_amount": hodl_asset_amount, "hodl_asset_value_at_sell": hodl_asset_value_at_sell
                                })
                                state_manager.record_partial_sell(
                                    original_trade_id=trade_id, remaining_quantity=hodl_asset_amount, sell_data=sell_result
                                )
                                live_portfolio_manager.get_total_portfolio_value(current_price, force_recalculation=True)
                            else:
                                logger.error(f"Sell execution failed for position {trade_id}.")

                # --- BUY LOGIC ---
                market_data = final_candle.to_dict()
                cash_balance = Decimal(self.trader.get_account_balance(asset=quote_asset))
                buy_from_reversal = False

                if self.is_monitoring_for_reversal:
                    # Check for timeout
                    if time.time() - self.monitoring_started_at > self.reversal_monitoring_timeout_seconds:
                        logger.info("Reversal monitoring timed out. Resetting state.")
                        self.is_monitoring_for_reversal = False
                        self.lowest_price_since_monitoring_started = None
                        self.monitoring_started_at = None
                        continue

                    # Check for new low
                    if current_price < self.lowest_price_since_monitoring_started:
                        logger.info(f"New low detected during reversal monitoring: {current_price:.2f}")
                        self.lowest_price_since_monitoring_started = current_price
                        self.monitoring_started_at = time.time()  # Reset timeout

                    # Check for reversal
                    reversal_target_price = self.lowest_price_since_monitoring_started * (1 + self.reversal_buy_threshold_percent)
                    if current_price >= reversal_target_price:
                        logger.info(f"Reversal detected! Price {current_price:.2f} crossed target {reversal_target_price:.2f}.")
                        buy_from_reversal = True
                        self.is_monitoring_for_reversal = False
                    else:
                        logger.info(f"Monitoring for reversal. Low: {self.lowest_price_since_monitoring_started:.2f}, Target: {reversal_target_price:.2f}")
                        # Skip normal buy/sell evaluation this cycle
                        time.sleep(30)
                        continue

                # Determine buy amount and operating mode
                buy_amount_usdt, operating_mode, reason, regime = capital_manager.get_buy_order_details(
                    market_data=market_data,
                    open_positions=open_positions,
                    portfolio_value=total_portfolio_value,
                    free_cash=cash_balance,
                    params=current_params,
                    trade_history=trade_history,
                    force_buy_signal=buy_from_reversal,
                    forced_reason="Buy triggered by price reversal."
                )

                # If the signal is to start monitoring, update state and skip buying this cycle
                if regime == "START_MONITORING" and not self.is_monitoring_for_reversal:
                    self.is_monitoring_for_reversal = True
                    self.lowest_price_since_monitoring_started = current_price
                    self.monitoring_started_at = time.time()
                    logger.info(f"Starting to monitor for buy reversal. Reason: {reason}")

                elif buy_amount_usdt > 0:
                    logger.info(f"[{operating_mode}] Buy signal triggered: {reason}. Preparing to buy ${buy_amount_usdt:,.2f} USD.")
                    if buy_amount_usdt < self.min_trade_size:
                        logger.warning(f"Proposed buy amount ${buy_amount_usdt:,.2f} is less than minimum trade size ${self.min_trade_size:,.2f}. Aborting.")
                    else:
                        decision_context = {
                            "operating_mode": operating_mode,
                            "buy_trigger_reason": reason,
                            "market_regime": int(current_regime)  # Cast to int to ensure JSON serialization
                        }
                        success, buy_result = self.trader.execute_buy(buy_amount_usdt, self.run_id, decision_context)

                        if success:
                            logger.info("Buy successful. Creating new position.")
                            purchase_price = Decimal(buy_result.get('price'))
                            sell_target_price = strategy_rules.calculate_sell_target_price(purchase_price, params=current_params)
                            logger.info(f"Calculated sell target for strategy buy. Purchase price: ${purchase_price:,.2f}, Target price: ${sell_target_price:,.2f}, Params: {current_params}")
                            state_manager.create_new_position(buy_result, sell_target_price)
                            live_portfolio_manager.get_total_portfolio_value(purchase_price, force_recalculation=True)
                else:
                    logger.info(f"[{operating_mode}] No buy signal: {reason}")

                # Calculate buy progress for TUI display
                buy_target, buy_progress = self._calculate_buy_progress(market_data, len(open_positions), current_params)

                # Persist the latest status to the database for the TUI
                status_service.update_bot_status(
                    bot_id=self.run_id,
                    mode=self.mode,
                    reason=reason,
                    open_positions=len(open_positions),
                    portfolio_value=total_portfolio_value,
                    market_regime=current_regime,
                    operating_mode=operating_mode,
                    buy_target=buy_target,
                    buy_progress=buy_progress
                )

                logger.info("--- Cycle complete. Waiting 30 seconds...")
                time.sleep(30)

            except KeyboardInterrupt:
                self.is_running = False
                logger.info("\n[SHUTDOWN] Ctrl+C detected.")
            except Exception as e:
                logger.critical(f"❌ Critical error in main loop: {e}", exc_info=True)
                time.sleep(300)

    def shutdown(self):
        logger.info("[SHUTDOWN] Initiating graceful shutdown...")
        logger.info("[SHUTDOWN] Cleanup complete. Goodbye!")