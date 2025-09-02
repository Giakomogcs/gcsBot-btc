import time
import uuid
import json
import os
import tempfile
from datetime import datetime, timedelta
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

        # --- Initialize Core Components ---
        # These are initialized here to be accessible throughout the bot's lifecycle (e.g., for status updates)
        self.feature_calculator = LiveFeatureCalculator(self.db_manager, mode=self.mode)
        self.status_service = StatusService(self.db_manager, config_manager, self.feature_calculator)
        self.state_manager = StateManager(mode=self.mode, bot_id=self.run_id, db_manager=self.db_manager, feature_calculator=self.feature_calculator)
        self.account_manager = AccountManager(self.trader.client)
        self.strategy_rules = StrategyRules(config_manager)
        self.capital_manager = CapitalManager(config_manager, self.strategy_rules)

        equity_recalc_interval = int(config_manager.get('APP', 'equity_recalculation_interval', fallback=300))
        quote_asset = "USDT"
        self.live_portfolio_manager = LivePortfolioManager(self.trader, self.state_manager, self.db_manager, quote_asset, equity_recalc_interval)

        self.dynamic_params = DynamicParameters(config_manager)
        self.sa_instance = SituationalAwareness()


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
                                purchase_price = Decimal(str(buy_result.get('price')))
                                quantity = Decimal(str(buy_result.get('quantity')))
                                sell_target_price = strategy_rules.calculate_sell_target_price(purchase_price, quantity)
                                logger.info(f"Calculated sell target for manual buy. Purchase price: ${purchase_price:,.2f}, Target price: ${sell_target_price:,.2f}")
                                state_manager.create_new_position(buy_result, sell_target_price)
                            else:
                                logger.error(f"Manual buy for ${amount_usd:.2f} failed. See trader logs for details (e.g., insufficient funds).")

                elif cmd_type == "force_sell":
                    trade_id = command.get("trade_id")
                    percentage = Decimal(command.get("percentage", "100.0"))
                    if not trade_id:
                        logger.error("Invalid 'force_sell' command: 'trade_id' is missing.")
                        os.remove(filepath) # Remove invalid command
                        continue

                    position = next((p for p in state_manager.get_open_positions() if p.trade_id == trade_id), None)

                    if not position:
                        logger.error(f"Cannot force sell: Trade with ID '{trade_id}' not found in open positions.")
                        os.remove(filepath) # Remove invalid command
                        continue

                    logger.info(f"Processing force sell for {percentage}% of trade {trade_id}.")
                    quantity_to_sell = Decimal(str(position.quantity)) * (percentage / Decimal("100"))

                    # Pre-flight check 1: Ensure quantity is positive
                    if quantity_to_sell <= 0:
                        logger.error(f"Calculated quantity to sell for trade {trade_id} is zero or less. Aborting.")
                        os.remove(filepath)
                        continue

                    # Pre-flight check 2: Notional value check
                    # We need the current price to perform this check
                    current_price_str = self.trader.get_current_price(self.symbol)
                    if current_price_str:
                        current_price = Decimal(current_price_str)
                        notional_value = quantity_to_sell * current_price
                        min_notional_value = self.trader.min_notional

                        if notional_value < min_notional_value:
                            logger.error(
                                f"Force sell command for trade {trade_id} aborted. "
                                f"Notional value (${notional_value:,.2f}) is below the minimum required "
                                f"by the exchange (${min_notional_value:,.2f})."
                            )
                            os.remove(filepath) # Remove the command to prevent retries
                            continue
                    else:
                        logger.warning("Could not fetch current price to validate notional value. Skipping check.")

                    logger.info(f"Executing force sell for trade {trade_id}, quantity: {quantity_to_sell:.8f}")
                    sell_position_data = position.to_dict()
                    sell_position_data['quantity'] = quantity_to_sell

                    success, sell_result = trader.execute_sell(sell_position_data, self.run_id, {"reason": "manual_force_sell"})

                    if success:
                        logger.info(f"Force sell for trade {trade_id} executed successfully on the exchange.")
                        buy_price = Decimal(str(position.price))

                        # --- Robust Decimal Conversion ---
                        # Validate sell_price before conversion
                        sell_price_raw = sell_result.get('price')
                        if sell_price_raw is None or str(sell_price_raw).strip() == '':
                            logger.error(f"Force sell price for trade {trade_id} was missing or empty. Using 0.0 as fallback for PnL.")
                            sell_price = Decimal('0.0')
                        else:
                            sell_price = Decimal(str(sell_price_raw))

                        # Validate sell_commission_usd before conversion
                        sell_commission_raw = sell_result.get('commission_usd')
                        if sell_commission_raw is None or str(sell_commission_raw).strip() == '':
                            logger.warning(f"Force sell commission for trade {trade_id} was missing or empty. Using 0.0 as fallback.")
                            sell_commission_usd = Decimal('0.0')
                        else:
                            sell_commission_usd = Decimal(str(sell_commission_raw))
                        # --- End Robust Decimal Conversion ---

                        realized_pnl_usd = strategy_rules.calculate_realized_pnl(
                            buy_price=buy_price,
                            sell_price=sell_price,
                            quantity_sold=quantity_to_sell,
                            buy_commission_usd=Decimal(str(position.commission_usd or '0')),
                            sell_commission_usd=sell_commission_usd,
                            buy_quantity=Decimal(str(position.quantity))
                        )

                        state_manager.close_forced_position(trade_id, sell_result, realized_pnl_usd)
                        logger.info(f"Successfully closed trade {trade_id} via force sell with PnL ${realized_pnl_usd:.2f}.")
                        os.remove(filepath) # Command succeeded, remove it.
                    else:
                        # If the sell fails, we DO NOT remove the command file.
                        # This allows the bot to retry on the next cycle, making the feature more robust.
                        logger.error(f"Manual sell for trade {trade_id} failed. See trader logs. The command will be retried.")

                else:
                    # For any other command type, we assume it's processed instantly and should be removed.
                    os.remove(filepath)
            except Exception as e:
                logger.error(f"Error processing command file {filename}: {e}", exc_info=True)
                # Attempt to remove the problematic file to prevent loop
                try:
                    os.remove(filepath)
                    logger.warning(f"Removed problematic command file {filepath} to prevent command loop.")
                except OSError as a:
                    logger.error(f"Could not remove problematic command file {filepath}: {a}")

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

    def _check_and_handle_refresh_signal(self):
        """Checks for a TUI-initiated refresh signal and triggers a status update if found."""
        signal_file_path = os.path.join("/app/.tui_files", f".force_refresh_{self.bot_name}")
        if os.path.exists(signal_file_path):
            logger.info(f"Force refresh signal detected at '{signal_file_path}'. Updating status file now.")
            try:
                # Call the self-contained update function
                self._update_status_file()
                # Clean up the signal file
                os.remove(signal_file_path)
                logger.info("Force refresh complete and signal file removed.")
            except Exception as e:
                logger.error(f"Error during forced refresh: {e}", exc_info=True)
                # Still try to remove the file to prevent getting stuck in a loop
                try:
                    os.remove(signal_file_path)
                except OSError:
                    pass

    def run(self):
        if self.mode not in ['trade', 'test']:
            logger.error(f"The 'run' method cannot be called in '{self.mode}' mode.")
            return

        base_asset = self.symbol.replace("USDT", "")

        # Reversal strategy specific configs
        self.reversal_buy_threshold_percent = Decimal(config_manager.get('STRATEGY_RULES', 'reversal_buy_threshold_percent', fallback='0.005'))
        self.reversal_monitoring_timeout_seconds = int(config_manager.get('STRATEGY_RULES', 'reversal_monitoring_timeout_seconds', fallback='300'))

        # The SituationalAwareness model is rule-based and doesn't require a separate training step.
        # Its transform method calculates regimes dynamically based on the data provided.
        logger.info("Situational Awareness model is rule-based and ready.")

        if not self.trader.is_ready:
            logger.critical("Trader could not be initialized. Shutting down bot.")
            self.shutdown()
            return

        self.state_manager.sync_holdings_with_binance(self.account_manager, self.strategy_rules, self.trader)

        # Perform an initial target recalculation after sync and before starting the main loop
        logger.info("Performing initial recalculation of sell targets before starting main loop...")
        self.state_manager.recalculate_open_position_targets(self.strategy_rules, self.sa_instance, self.dynamic_params)
        logger.info("Initial recalculation complete.")

        # Now that initialization is complete, set the status to RUNNING
        self.status_service.set_bot_running(self.bot_name, self.mode)
        logger.info(f"🚀 --- TRADING BOT STARTED --- BOT NAME: {self.bot_name} --- RUN ID: {self.run_id} --- SYMBOL: {self.symbol} --- MODE: {self.mode.upper()} --- 🚀")

        try:
            while self.is_running:
                try:
                    self._check_and_handle_refresh_signal()
                    
                    logger.info("--- Starting new trading cycle ---")
                    self.state_manager.recalculate_open_position_targets(self.strategy_rules, self.sa_instance, self.dynamic_params)
                    self._handle_ui_commands(self.trader, self.state_manager, self.strategy_rules)

                    features_df = self.feature_calculator.get_features_dataframe()
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
                    if self.sa_instance:
                        try:
                            # Pass the full dataframe to transform
                            regime_df = self.sa_instance.transform(features_df)
                            if not regime_df.empty:
                                # Get the regime from the last row
                                current_regime = int(regime_df['market_regime'].iloc[-1])
                                logger.info(f"Current market regime detected: {current_regime}")
                            else:
                                logger.warning("Could not determine market regime from candle.")
                        except Exception as e:
                            logger.error(f"Error getting market regime: {e}", exc_info=True)

                    self.dynamic_params.update_parameters(current_regime)
                    current_params = self.dynamic_params.parameters
                    logger.info(f"Using strategy parameters for Regime {current_regime}: {current_params}")

                    current_price = Decimal(final_candle['close'])
                    open_positions = self.state_manager.get_open_positions()
                    total_portfolio_value = self.live_portfolio_manager.get_total_portfolio_value(current_price)

                    all_prices = self.trader.get_all_prices()
                    wallet_balances = self.account_manager.get_all_account_balances(all_prices)

                    # Fetch recent trades for difficulty calculation
                    end_date = datetime.utcnow()
                    start_date = end_date - timedelta(hours=self.capital_manager.difficulty_reset_timeout_hours)
                    trade_history = self.db_manager.get_all_trades_in_range(
                        mode=self.mode,
                        start_date=start_date,
                        end_date=end_date
                    )

                    # For the state file, we might still want the full history
                    full_trade_history = self.state_manager.get_trade_history_for_run()
                    self._write_state_to_file(open_positions, current_price, wallet_balances, full_trade_history, total_portfolio_value)

                    # --- SELL LOGIC (Trailing Take-Profit) ---
                    positions_to_sell = []
                    for position in open_positions:
                        # Ensure sell_target_price is a Decimal
                        sell_target_price = Decimal(str(position.sell_target_price or 'inf'))

                        # 1. Check if the initial profit target has been breached
                        if not position.profit_target_breached and current_price >= sell_target_price:
                            logger.info(f"Trailing Stop Activated for trade {position.trade_id}. Initial target ${sell_target_price:,.2f} breached at price ${current_price:,.2f}.")
                            update_data = {
                                "profit_target_breached": True,
                                "highest_price_since_breach": current_price
                            }
                            self.db_manager.update_trade(position.trade_id, update_data)
                            # Update the in-memory object as well
                            position.profit_target_breached = True
                            position.highest_price_since_breach = current_price

                        # 2. If trailing is active, manage the high-water mark and check for stop loss
                        elif position.profit_target_breached:
                            highest_price = Decimal(str(position.highest_price_since_breach))
                            if current_price > highest_price:
                                logger.info(f"Trailing Stop for trade {position.trade_id}: New high price reached ${current_price:,.2f} (old: ${highest_price:,.2f}).")
                                self.db_manager.update_trade(position.trade_id, {"highest_price_since_breach": current_price})
                                # Update in-memory object
                                position.highest_price_since_breach = current_price
                            else:
                                trailing_stop_price = highest_price * (Decimal('1') - self.strategy_rules.trailing_stop_percent)
                                logger.info(f"Checking trailing stop for {position.trade_id}: Current ${current_price:,.2f}, High ${highest_price:,.2f}, Stop Trigger ${trailing_stop_price:,.2f}")
                                if current_price <= trailing_stop_price:
                                    logger.info(f"Trailing Stop Triggered for trade {position.trade_id}. Selling.")
                                    positions_to_sell.append(position)

                    if positions_to_sell:
                        logger.info(f"Found {len(positions_to_sell)} positions meeting sell criteria based on trailing stop.")
                        total_sell_quantity = sum(Decimal(str(p.quantity)) * self.strategy_rules.sell_factor for p in positions_to_sell)
                        available_balance = Decimal(self.trader.get_account_balance(asset=base_asset))

                        if total_sell_quantity > available_balance:
                            logger.critical(
                                f"INSUFFICIENT BALANCE & STATE DESYNC: Attempting to sell {total_sell_quantity:.8f} {base_asset}, "
                                f"but only {available_balance:.8f} is available on the exchange. "
                                "This indicates a significant discrepancy between the bot's state and the exchange's reality. "
                                "The bot will NOT proceed with the sell and will wait for the next sync cycle to correct the state."
                            )
                        else:
                            for position in positions_to_sell:
                                trade_id = position.trade_id
                                original_quantity = Decimal(str(position.quantity))
                                # sell_factor determines what percentage of the position to sell
                                sell_quantity = original_quantity * self.strategy_rules.sell_factor
                                hodl_asset_amount = original_quantity - sell_quantity

                                sell_position_data = position.to_dict()
                                sell_position_data['quantity'] = sell_quantity

                                success, sell_result = self.trader.execute_sell(sell_position_data, self.run_id, final_candle.to_dict())
                                if success:
                                    buy_price = Decimal(str(position.price))
                                    
                                    # --- Robust Decimal Conversion ---
                                    # Validate sell_price before conversion
                                    sell_price_raw = sell_result.get('price')
                                    if sell_price_raw is None or str(sell_price_raw).strip() == '':
                                        logger.error(f"Sell price for trade {trade_id} was missing or empty in the exchange response. Using 0.0 as fallback for PnL calculation.")
                                        sell_price = Decimal('0.0')
                                    else:
                                        sell_price = Decimal(str(sell_price_raw))

                                    # Validate sell_commission_usd before conversion
                                    sell_commission_raw = sell_result.get('commission_usd')
                                    if sell_commission_raw is None or str(sell_commission_raw).strip() == '':
                                        logger.warning(f"Sell commission for trade {trade_id} was missing or empty. Using 0.0 as fallback.")
                                        sell_commission_usd = Decimal('0.0')
                                    else:
                                        sell_commission_usd = Decimal(str(sell_commission_raw))
                                    # --- End Robust Decimal Conversion ---

                                    # PnL is calculated based on the quantity *actually* sold
                                    realized_pnl_usd = self.strategy_rules.calculate_realized_pnl(
                                        buy_price=buy_price,
                                        sell_price=sell_price,
                                        quantity_sold=sell_quantity,
                                        buy_commission_usd=Decimal(str(position.commission_usd or '0')),
                                        sell_commission_usd=sell_commission_usd,
                                        buy_quantity=Decimal(str(position.quantity))
                                    )
                                    hodl_asset_value_at_sell = hodl_asset_amount * current_price

                                    sell_result.update({
                                        "realized_pnl_usd": realized_pnl_usd,
                                        "hodl_asset_amount": hodl_asset_amount,
                                        "hodl_asset_value_at_sell": hodl_asset_value_at_sell
                                    })

                                    # The new logic handles partial sells correctly
                                    self.state_manager.record_partial_sell(
                                        original_trade_id=trade_id,
                                        remaining_quantity=hodl_asset_amount,
                                        sell_data=sell_result
                                    )
                                    self.live_portfolio_manager.get_total_portfolio_value(current_price, force_recalculation=True)
                                else:
                                    logger.error(f"Sell execution failed for position {trade_id}.")

                    # --- BUY LOGIC ---
                    market_data = final_candle.to_dict()
                    cash_balance = Decimal(self.trader.get_account_balance("USDT"))
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
                    buy_amount_usdt, operating_mode, reason, regime = self.capital_manager.get_buy_order_details(
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
                                purchase_price = Decimal(str(buy_result.get('price')))
                                quantity = Decimal(str(buy_result.get('quantity')))
                                sell_target_price = self.strategy_rules.calculate_sell_target_price(purchase_price, quantity, params=current_params)
                                logger.info(f"Calculated sell target for strategy buy. Purchase price: ${purchase_price:,.2f}, Target price: ${sell_target_price:,.2f}, Params: {current_params}")
                                self.state_manager.create_new_position(buy_result, sell_target_price)
                                self.live_portfolio_manager.get_total_portfolio_value(purchase_price, force_recalculation=True)
                    else:
                        logger.info(f"[{operating_mode}] No buy signal: {reason}")

                    # Update the status file at the end of the regular cycle
                    self._update_status_file()
                    
                    logger.info("--- Cycle complete. Waiting 30 seconds...")
                    time.sleep(30)

                except NameError as e:
                    logger.critical(f"❌ A 'NameError' occurred in the main loop. This is often a typo in a variable name or an uninitialized variable.", exc_info=True)
                    time.sleep(60) # Sleep for a bit to avoid spamming logs if the error is persistent
                except KeyboardInterrupt:
                    self.is_running = False
                    logger.info("\n[SHUTDOWN] Ctrl+C detected.")
                except Exception as e:
                    logger.critical(f"❌ Critical error in main loop: {e}", exc_info=True)
                    time.sleep(300)
        finally:
            self.shutdown()

    def _update_status_file(self):
        """
        Gathers the bot's current state by re-running calculations and writes it to the JSON file for the TUI.
        This is a self-contained method that can be called at any time to refresh the status.
        """
        logger.info("Starting status file update...")
        try:
            # 1. Get latest market data
            features_df = self.feature_calculator.get_features_dataframe()
            if features_df.empty:
                logger.warning("Could not get features dataframe for status update.")
                return
            final_candle = features_df.iloc[-1]
            if final_candle.isnull().any():
                logger.warning("Final candle contains NaN values during status update.")
                return
            market_data = final_candle.to_dict()
            current_price = Decimal(final_candle['close'])

            # 2. Get latest positions and portfolio value
            open_positions = self.state_manager.get_open_positions()
            total_portfolio_value = self.live_portfolio_manager.get_total_portfolio_value(current_price, force_recalculation=True)
            cash_balance = Decimal(self.trader.get_account_balance("USDT"))

            # 3. Get latest regime and parameters
            current_regime = -1
            if self.sa_instance:
                regime_df = self.sa_instance.transform(features_df)
                if not regime_df.empty:
                    current_regime = int(regime_df['market_regime'].iloc[-1])
            self.dynamic_params.update_parameters(current_regime)
            current_params = self.dynamic_params.parameters

            # 4. Determine current "reason" text by re-evaluating capital manager logic
            end_date = datetime.utcnow()
            start_date = end_date - timedelta(hours=self.capital_manager.difficulty_reset_timeout_hours)
            trade_history = self.db_manager.get_all_trades_in_range(mode=self.mode, start_date=start_date, end_date=end_date)
            
            _, operating_mode, reason, _ = self.capital_manager.get_buy_order_details(
                market_data=market_data, open_positions=open_positions, portfolio_value=total_portfolio_value,
                free_cash=cash_balance, params=current_params, trade_history=trade_history
            )

            # 5. Calculate buy progress
            buy_target, buy_progress = self._calculate_buy_progress(market_data, len(open_positions), current_params)

            # 6. Persist the latest status to the database for the TUI
            self.status_service.update_bot_status(
                bot_id=self.bot_name, mode=self.mode, reason=reason, open_positions=len(open_positions),
                portfolio_value=total_portfolio_value, market_regime=current_regime, operating_mode=operating_mode,
                buy_target=buy_target, buy_progress=buy_progress
            )

            # 7. Write the live status file
            status_dir = "/app/.tui_files"
            # Ensure the directory exists and has permissions that allow writing from different users (e.g., inside and outside Docker)
            os.makedirs(status_dir, mode=0o777, exist_ok=True)
            status_file_path = os.path.join(status_dir, f".bot_status_{self.bot_name}.json")
            status_data = self.status_service.get_extended_status(self.mode, self.bot_name)
            portfolio_history = self.db_manager.get_portfolio_history(self.bot_name)
            status_data['portfolio_history'] = [p.to_dict() for p in portfolio_history]
            
            temp_path = status_file_path + ".tmp"
            with open(temp_path, "w") as f:
                json.dump(status_data, f, default=str)
            os.rename(temp_path, status_file_path)
            logger.info("Status file update complete.")

        except Exception as e:
            logger.error(f"Failed to write status file for TUI during update: {e}", exc_info=True)

    def shutdown(self):
        logger.info("[SHUTDOWN] Initiating graceful shutdown...")
        if hasattr(self, 'status_service'):
            self.status_service.set_bot_stopped(self.bot_name)
        logger.info("[SHUTDOWN] Cleanup complete. Goodbye!")