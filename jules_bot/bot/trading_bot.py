import time
from typing import Optional
import uuid
import json
import os
import shutil
import tempfile
import threading
import uvicorn
from fastapi import FastAPI
from datetime import datetime, timedelta
from decimal import Decimal, getcontext, InvalidOperation
from jules_bot.utils.logger import logger
from jules_bot.utils.config_manager import config_manager
from jules_bot.bot.synchronization_manager import SynchronizationManager
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
from jules_bot.utils.helpers import _calculate_progress_pct, calculate_buy_progress
from jules_bot.bot.api import router as api_router

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
        self.cached_cash_balance = Decimal('0.0')
        self.cached_open_positions_value = Decimal('0.0')
        self.symbol = config_manager.get('APP', 'symbol')

    def get_total_portfolio_value(self, current_price: Decimal, force_recalculation: bool = False) -> Decimal:
        current_time = time.time()
        if force_recalculation or (current_time - self.last_recalculation_time > self.recalculation_interval):
            logger.info("Recalculating portfolio equity...")
            try:
                self.cached_cash_balance = Decimal(self.trader.get_account_balance(asset=self.quote_asset))
                open_positions = self.state_manager.get_open_positions()

                self.cached_open_positions_value = sum(
                    Decimal(p.remaining_quantity) * current_price for p in open_positions
                )

                self.cached_portfolio_value = self.cached_cash_balance + self.cached_open_positions_value
                self.last_recalculation_time = current_time
                logger.info(f"Portfolio equity recalculated: ${self.cached_portfolio_value:,.2f}")

                self._create_db_snapshot(self.cached_cash_balance, self.cached_open_positions_value, current_price)

            except Exception as e:
                logger.error(f"Error during portfolio value calculation: {e}", exc_info=True)
                return self.cached_portfolio_value

        return self.cached_portfolio_value

    def _create_db_snapshot(self, usd_balance: Decimal, open_positions_value_usd: Decimal, current_price: Decimal):
        try:
            total_portfolio_value_usd = usd_balance + open_positions_value_usd

            # Fetch ONLY closed sell trades for accurate PnL and treasury calculation
            closed_sell_trades = self.db_manager.get_closed_sell_trades_for_run(run_id=self.state_manager.bot_id)

            realized_pnl_usd = sum(Decimal(str(t.realized_pnl_usd or '0')) for t in closed_sell_trades)
            btc_treasury_amount = sum(Decimal(str(t.hodl_asset_amount or '0')) for t in closed_sell_trades)

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
        self.is_syncing = True  # Start in syncing state
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
        self.capital_manager = CapitalManager(config_manager, self.strategy_rules, self.db_manager)

        equity_recalc_interval = int(config_manager.get('APP', 'equity_recalculation_interval', fallback=300))
        quote_asset = "USDT"
        self.live_portfolio_manager = LivePortfolioManager(self.trader, self.state_manager, self.db_manager, quote_asset, equity_recalc_interval)

        self.dynamic_params = DynamicParameters(config_manager)
        self.sa_instance = SituationalAwareness()

        # --- Synchronization Manager ---
        logger.info("Initializing SynchronizationManager for periodic checks...")
        self.sync_manager = SynchronizationManager(
            binance_client=self.trader.client,
            db_manager=self.db_manager,
            symbol=self.symbol,
            strategy_rules=self.strategy_rules,
            environment=self.mode
        )
        self.last_sync_time = None # Initialize to run sync on first cycle

        # API Setup
        self.api_app = FastAPI(title=f"Jules Bot API - {self.bot_name}")
        self.api_app.state.bot = self  # Make bot instance available to endpoints
        self.api_app.include_router(api_router, prefix="/api")
        self.api_port = int(os.getenv('API_PORT', '8766'))

        # State for TUI synchronization
        self.last_decision_reason: str = "Initializing..."
        self.last_operating_mode: str = "STARTUP"
        self.last_difficulty_factor: Decimal = Decimal('0')

        # State for Regime Fallback
        self.last_known_regime = -1
        self.last_known_regime_timestamp = None

    def process_force_buy(self, amount_usd: str):
        """Processes a force buy command received from the API."""
        try:
            amount_decimal = Decimal(amount_usd)
        except InvalidOperation:
            logger.error(f"Invalid number format for force buy: {amount_usd}")
            return {"status": "error", "message": "Invalid number format provided."}

        logger.info(f"▶️ API command received: Force buy for ${amount_decimal:.2f}")
        # Basic validation
        if amount_decimal < self.min_trade_size:
            logger.error(f"Manual buy for ${amount_decimal:.2f} is below min trade size ${self.min_trade_size:.2f}.")
            return {"status": "error", "message": "Amount is below minimum trade size."}

        logger.info("▶️ Sending force buy command...")
        success, buy_result = self.trader.execute_buy(float(amount_decimal), self.run_id, {"reason": "manual_api_override"})
        if success:
            purchase_price = Decimal(str(buy_result.get('price', '0')))
            quantity_bought = Decimal(str(buy_result.get('quantity', '0')))

            if purchase_price <= 0 or quantity_bought <= 0:
                logger.critical(f"Could not execute force_buy. Invalid trade data received: price={purchase_price}, quantity={quantity_bought}")
                return {"status": "error", "message": "Invalid trade data received from exchange."}

            logger.info(f"✅ Force buy successful: Qty={quantity_bought:.8f}, AvgPrice=${purchase_price:,.2f}")

            # Use default params for sell target calculation on manual override
            sell_target_price = self.strategy_rules.calculate_sell_target_price(purchase_price, quantity_bought, params=None)
            self.state_manager.create_new_position(buy_result, sell_target_price)
            logger.info("Force buy executed and position created successfully. Updating status file.")
            self._update_status_file()  # Update TUI immediately
            return {"status": "success", "trade_details": buy_result}
        else:
            logger.error(f"Force buy for ${amount_decimal:.2f} failed during execution.")
            return {"status": "error", "message": "Trader failed to execute buy."}

    def process_force_sell(self, trade_id: str, percentage: str):
        """Processes a force sell command received from the API."""
        try:
            # Clean the percentage string by removing '%' and stripping whitespace
            cleaned_percentage_str = percentage.strip().replace('%', '')
            percentage_decimal = Decimal(cleaned_percentage_str)
        except InvalidOperation:
            logger.error(f"Invalid number format for force sell percentage: {percentage}")
            return {"status": "error", "message": "Invalid number format for percentage."}

        logger.info(f"▶️ API command received: Force sell for {percentage_decimal}% of trade {trade_id}")
        position = next((p for p in self.state_manager.get_open_positions() if p.trade_id == trade_id), None)

        if not position:
            logger.error(f"Cannot force sell: Trade ID '{trade_id}' not found.")
            return {"status": "error", "message": f"Trade ID '{trade_id}' not found."}

        # The rest of the logic is similar to the file-based one, adapted for direct execution
        quantity_to_sell = Decimal(str(position.remaining_quantity)) * (percentage_decimal / Decimal("100"))

        # --- MINIMUM QUANTITY VALIDATION ---
        if self.trader.min_qty is not None and quantity_to_sell < self.trader.min_qty:
            msg = (
                f"Calculated quantity to sell ({quantity_to_sell:.8f}) is below the exchange minimum "
                f"({self.trader.min_qty:.8f}). Please choose a larger percentage."
            )
            logger.error(f"Force sell aborted: {msg}")
            return {"status": "error", "message": msg}

        # Validation checks
        current_price_str = self.trader.get_current_price(self.symbol)
        if current_price_str:
            notional_value = quantity_to_sell * Decimal(current_price_str)
            if notional_value < self.trader.min_notional:
                msg = f"Notional value (${notional_value:,.2f}) is below exchange minimum (${self.trader.min_notional:,.2f})."
                logger.error(f"Force sell aborted: {msg}")
                return {"status": "error", "message": msg}

        sell_position_data = position.to_dict()
        sell_position_data['quantity'] = quantity_to_sell

        logger.info("▶️ Sending force sell command...")
        success, sell_result = self.trader.execute_sell(sell_position_data, self.run_id, {"reason": "manual_api_force_sell"})

        if success:
            logger.info("✅ Force sell successful. Calculating PnL...")
            buy_price = Decimal(str(position.price))
            sell_price = Decimal(str(sell_result.get('price', '0')))
            sell_commission_usd = Decimal(str(sell_result.get('commission_usd', '0')))
            realized_pnl_usd = self.strategy_rules.calculate_realized_pnl(
                buy_price, sell_price, quantity_to_sell,
                Decimal(str(position.commission_usd or '0')),
                sell_commission_usd, Decimal(str(position.quantity))
            )
            self.state_manager.close_forced_position(trade_id, sell_result, realized_pnl_usd)
            logger.info(f"Force sell for trade {trade_id} executed successfully. Updating status file.")
            self._update_status_file()  # Update TUI immediately
            return {"status": "success", "pnl_usd": f"{realized_pnl_usd:.2f}", "trade_details": sell_result}
        else:
            logger.error(f"Force sell for trade {trade_id} failed during execution.")
            return {"status": "error", "message": "Trader failed to execute sell."}

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

    def _check_and_handle_refresh_signal(self):
        """Checks for a TUI-initiated refresh signal and triggers a status update if found."""
        signal_file_path = os.path.join(".tui_files", f".force_refresh_{self.bot_name}")
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

    def _execute_sell_candidates(self, sell_candidates, current_price, base_asset, market_data):
        logger.info(f"Found {len(sell_candidates)} candidates for selling. Performing final profitability check...")
        positions_to_sell_now = []
        for position, reason in sell_candidates:
            entry_price = Decimal(str(position.price))
            break_even_price = self.strategy_rules.calculate_break_even_price(entry_price)
            if current_price > break_even_price:
                logger.info(f"✅ Position {position.trade_id} is PROFITABLE. Current price ${current_price:,.2f} > Break-even price ${break_even_price:,.2f}. Marking for sale.")
                positions_to_sell_now.append(position)
            else:
                logger.warning(f"❌ SALE CANCELED for position {position.trade_id}. Reason: {reason}. Current price ${current_price:,.2f} is not above break-even price ${break_even_price:,.2f}.")
                if reason == 'trailing_stop' and position.is_smart_trailing_active:
                    logger.warning(f"RESETTING SMART TRAILING for {position.trade_id} to prevent loss.")
                    self.state_manager.update_trade_smart_trailing_state(trade_id=position.trade_id, is_active=False, highest_profit=Decimal('0'), activation_price=None)
                    position.is_smart_trailing_active = False

        if not positions_to_sell_now:
            return

        logger.info(f"Found {len(positions_to_sell_now)} positions that passed the final profitability check. Consolidating into a single sell order.")

        # --- Aggregation Logic ---
        # This logic assumes a sell_factor of 1 (100% sell). Partial sells are not compatible with this consolidated approach.
        total_quantity_to_sell = sum(Decimal(str(p.remaining_quantity)) for p in positions_to_sell_now)

        # --- Balance and Minimums Check ---
        available_balance = Decimal(self.trader.get_account_balance(asset=base_asset))
        if total_quantity_to_sell > available_balance:
            logger.critical(f"INSUFFICIENT BALANCE & STATE DESYNC: Attempting to sell {total_quantity_to_sell:.8f} {base_asset}, but only {available_balance:.8f} is available.")
            return

        notional_value = total_quantity_to_sell * current_price
        if notional_value < self.trader.min_notional:
            logger.warning(f"Consolidated sell aborted. Notional value ${notional_value:,.2f} is below exchange minimum ${self.trader.min_notional:,.2f}.")
            return

        # --- Single Sell Execution ---
        # Create a dummy trade_id for the consolidated sell log, it is not persisted.
        sell_data = {'quantity': total_quantity_to_sell, 'trade_id': str(uuid.uuid4())}
        success, sell_result = self.trader.execute_sell(sell_data, self.run_id, market_data)

        if not success:
            logger.error(f"Consolidated sell of {total_quantity_to_sell:.8f} {base_asset} failed. No positions will be closed.")
            # Optionally, record a failure for each individual trade
            error_reason = sell_result if (sell_result and 'error' in sell_result) else {"error": "Unknown consolidated sell error"}
            for position in positions_to_sell_now:
                self.state_manager.record_sell_failure(position.trade_id, error_reason)
            return

        # --- Process Results for Each Position Post-Sale ---
        logger.info(f"Consolidated sell successful. Processing {len(positions_to_sell_now)} individual positions.")
        avg_sell_price = Decimal(str(sell_result.get('price', '0')))
        total_commission_usd = Decimal(str(sell_result.get('commission_usd', '0')))

        for position in positions_to_sell_now:
            trade_id = position.trade_id
            quantity_sold = Decimal(str(position.remaining_quantity))

            # Pro-rate the commission for this specific position's contribution to the batch
            pro_rata_commission_usd = (total_commission_usd * quantity_sold) / total_quantity_to_sell if total_quantity_to_sell > 0 else Decimal('0')

            realized_pnl_usd = self.strategy_rules.calculate_realized_pnl(
                buy_price=Decimal(str(position.price)),
                sell_price=avg_sell_price,
                quantity_sold=quantity_sold,
                buy_commission_usd=Decimal(str(position.commission_usd or '0')),
                sell_commission_usd=pro_rata_commission_usd,
                buy_quantity=Decimal(str(position.quantity))
            )

            # Create a sell_result specific to this trade for record-keeping
            individual_sell_result = sell_result.copy()
            individual_sell_result.update({
                "realized_pnl_usd": realized_pnl_usd,
                "hodl_asset_amount": Decimal('0'), # Assumes 100% sell
                "hodl_asset_value_at_sell": Decimal('0')
            })
            
            # Since we sold 100%, we record a partial sell with 0 remaining quantity,
            # which will mark the original trade as CLOSED.
            self.state_manager.record_partial_sell(
                original_trade_id=trade_id,
                remaining_quantity=Decimal('0'),
                sell_data=individual_sell_result
            )

        # Recalculate portfolio value once at the end
        self.live_portfolio_manager.get_total_portfolio_value(current_price, force_recalculation=True)

    def _evaluate_and_execute_buy(self, market_data, open_positions, current_params, current_regime, current_price):
        cash_balance = Decimal(self.trader.get_account_balance("USDT"))
        buy_from_reversal = False

        if self.is_monitoring_for_reversal:
            if time.time() - self.monitoring_started_at > self.reversal_monitoring_timeout_seconds:
                logger.info("Reversal monitoring timed out. Resetting state.")
                self.is_monitoring_for_reversal = False
            elif current_price < self.lowest_price_since_monitoring_started:
                logger.info(f"New low detected during reversal monitoring: {current_price:.2f}")
                self.lowest_price_since_monitoring_started = current_price
                self.monitoring_started_at = time.time()
            elif current_price >= self.lowest_price_since_monitoring_started * (1 + self.reversal_buy_threshold_percent):
                logger.info(f"Reversal detected! Price {current_price:.2f} crossed target.")
                buy_from_reversal = True
                self.is_monitoring_for_reversal = False
            else:
                return # Skip normal buy evaluation this cycle

        end_date = datetime.utcnow()
        start_date = end_date - timedelta(hours=self.capital_manager.difficulty_reset_timeout_hours)
        trade_history = self.db_manager.get_all_trades_in_range(mode=self.mode, start_date=start_date, end_date=end_date, bot_id=self.run_id)

        total_portfolio_value = self.live_portfolio_manager.cached_portfolio_value
        buy_amount_usdt, operating_mode, reason, regime, difficulty_factor = self.capital_manager.get_buy_order_details(
            market_data=market_data, open_positions=open_positions, portfolio_value=total_portfolio_value,
            free_cash=cash_balance, params=current_params, trade_history=trade_history,
            force_buy_signal=buy_from_reversal, forced_reason="Buy triggered by price reversal."
        )
        self.last_decision_reason, self.last_operating_mode, self.last_difficulty_factor = reason, operating_mode, difficulty_factor

        if regime == "START_MONITORING" and not self.is_monitoring_for_reversal:
            self.is_monitoring_for_reversal = True
            self.lowest_price_since_monitoring_started = current_price
            self.monitoring_started_at = time.time()
            logger.info(f"Starting to monitor for buy reversal. Reason: {reason}")
        elif buy_amount_usdt > 0:
            logger.info(f"[{operating_mode}] Buy signal triggered: {reason}. Preparing to buy ${buy_amount_usdt:,.2f} USD.")
            if buy_amount_usdt >= self.min_trade_size:
                decision_context = {"operating_mode": operating_mode, "buy_trigger_reason": reason, "market_regime": int(current_regime)}
                success, buy_result = self.trader.execute_buy(buy_amount_usdt, self.run_id, decision_context)
                if success:
                    purchase_price = Decimal(str(buy_result.get('price', '0')))
                    quantity_bought = Decimal(str(buy_result.get('quantity', '0')))
                    if purchase_price > 0 and quantity_bought > 0:
                        sell_target_price = self.strategy_rules.calculate_sell_target_price(purchase_price, quantity_bought, params=current_params)
                        self.state_manager.create_new_position(buy_result, sell_target_price)
                        self.live_portfolio_manager.get_total_portfolio_value(purchase_price, force_recalculation=True)
                    else:
                        logger.critical(f"Could not execute buy. Invalid trade data received: price={purchase_price}, quantity={quantity_bought}")
            else:
                logger.warning(f"Proposed buy amount ${buy_amount_usdt:,.2f} is less than minimum trade size ${self.min_trade_size:,.2f}. Aborting.")

    def run(self):
        if self.mode not in ['trade', 'test']:
            logger.error(f"The 'run' method cannot be called in '{self.mode}' mode.")
            return
        base_asset = self.symbol.replace("USDT", "")
        self.reversal_buy_threshold_percent = Decimal(config_manager.get('STRATEGY_RULES', 'reversal_buy_threshold_percent', fallback='0.005'))
        self.reversal_monitoring_timeout_seconds = int(config_manager.get('STRATEGY_RULES', 'reversal_monitoring_timeout_seconds', fallback='300'))

        # Load Regime Fallback settings
        self.use_regime_fallback = config_manager.getboolean('STRATEGY_RULES', 'use_regime_fallback', fallback=True)
        self.regime_fallback_ttl_seconds = int(config_manager.get('STRATEGY_RULES', 'regime_fallback_ttl_seconds', fallback=300)) # 5 minutes

        logger.info("Situational Awareness model is rule-based and ready.")
        if not self.trader.is_ready:
            logger.critical("Trader could not be initialized. Shutting down bot.")
            return

        logger.info("Bot is starting initial synchronization. Trading is paused.")
        self.is_syncing = True
        self._update_sync_status_file()
        self.sync_manager.run_full_sync()
        self.is_syncing = False
        self._update_sync_status_file()
        logger.info("Initial synchronization complete. Trading is now enabled.")

        logger.info("Performing initial recalculation of sell targets before starting main loop...")
        self.state_manager.recalculate_open_position_targets(self.strategy_rules, self.sa_instance, self.dynamic_params)
        logger.info("Initial recalculation complete.")
        self.status_service.set_bot_running(self.bot_name, self.mode)
        uvicorn_config = uvicorn.Config(self.api_app, host="0.0.0.0", port=self.api_port, log_level="info")
        api_thread = threading.Thread(target=uvicorn.Server(config=uvicorn_config).run, daemon=True)
        api_thread.start()
        logger.info(f"🚀 --- TRADING BOT STARTED (API on port {self.api_port}) --- BOT NAME: {self.bot_name} --- RUN ID: {self.run_id} --- SYMBOL: {self.symbol} --- MODE: {self.mode.upper()} --- 🚀")
        last_recalc_time = 0
        last_status_update_time = 0
        try:
            while self.is_running:
                try:
                    now = datetime.now()
                    current_time = time.time()
                    if self.last_sync_time is None or (now - self.last_sync_time) > timedelta(minutes=30):
                        logger.info("Starting periodic trade history synchronization. Pausing trading.")
                        self.is_syncing = True
                        self._update_sync_status_file()
                        self.sync_manager.run_full_sync()
                        self.last_sync_time = now
                        self.is_syncing = False
                        self._update_sync_status_file()
                        logger.info("Periodic synchronization complete. Resuming trading.")
                    # Only run trading logic if the bot is not currently syncing
                    if not self.is_syncing:
                        if current_time - last_recalc_time > 60:
                            logger.info("--- Recalculating all open position sell targets ---")
                            self.state_manager.recalculate_open_position_targets(self.strategy_rules, self.sa_instance, self.dynamic_params)
                            last_recalc_time = current_time
                        self._check_and_handle_refresh_signal()
                        logger.info("--- Starting new trading cycle ---")
                        features_df = self.feature_calculator.get_features_dataframe()
                        if features_df.empty:
                            logger.warning("Could not get features dataframe. Skipping cycle.")
                            time.sleep(10)
                            continue
                        final_candle = features_df.iloc[-1]
                        if final_candle.isnull().any():
                            logger.warning(f"Final candle contains NaN values, skipping cycle. Data: {final_candle.to_dict()}")
                            time.sleep(10)
                            continue
                        market_data = final_candle.to_dict()
                        current_price = Decimal(final_candle['close'])
                        regime_df = self.sa_instance.transform(features_df)
                        
                        # Encontra o último regime válido, ignorando os -1s que podem aparecer no início do dataset
                        valid_regimes = regime_df[regime_df['market_regime'] != -1]['market_regime']
                        calculated_regime = int(valid_regimes.iloc[-1]) if not valid_regimes.empty else -1

                        current_regime = calculated_regime
                        regime_source = "Calculated"

                        # Se o regime calculado for indefinido, tenta usar o fallback
                        if calculated_regime == -1 and self.use_regime_fallback:
                            if self.last_known_regime != -1 and self.last_known_regime_timestamp is not None:
                                time_since_last_known = time.time() - self.last_known_regime_timestamp
                                if time_since_last_known < self.regime_fallback_ttl_seconds:
                                    current_regime = self.last_known_regime
                                    regime_source = f"Fallback (age: {time_since_last_known:.0f}s)"
                                    logger.warning(f"Regime indefinido. Usando último regime conhecido: {current_regime} de {time_since_last_known:.0f}s atrás.")
                                else:
                                    logger.warning(f"Regime indefinido. Último regime conhecido ({self.last_known_regime}) expirou ({time_since_last_known:.0f}s > {self.regime_fallback_ttl_seconds}s).")

                        # Se o regime atual (calculado ou fallback) for válido, atualiza o estado
                        if current_regime != -1:
                            self.last_known_regime = current_regime
                            self.last_known_regime_timestamp = time.time()

                        # Atualiza os parâmetros dinâmicos com o regime encontrado
                        self.dynamic_params.update_parameters(current_regime)

                        # Adiciona uma verificação para logar o regime atual e os parâmetros carregados
                        regime_name_map = {v: k for k, v in self.sa_instance.regime_map.items()}
                        regime_name = regime_name_map.get(current_regime, "UNDEFINED")
                        logger.info(f"Regime de mercado atual: {regime_name} ({current_regime}) | Fonte: {regime_source}. Parâmetros carregados.")
                        
                        if current_regime == -1:
                            logger.warning("Market regime is -1 (undefined) and fallback is disabled or expired. Skipping buy/sell logic for this cycle.")
                            time.sleep(10)
                            continue
                        current_params = self.dynamic_params.parameters
                        open_positions = self.state_manager.get_open_positions()
                        sell_candidates = []
                        for position in open_positions:
                            sell_target_price = Decimal(str(position.sell_target_price)) if position.sell_target_price is not None else Decimal('inf')
                            if current_price >= sell_target_price:
                                logger.info(f"✅ TAKE PROFIT HIT for position {position.trade_id} at ${current_price:,.2f} (Target: ${sell_target_price:,.2f}).")
                                sell_candidates.append((position, "take_profit"))
                                continue
                            net_unrealized_pnl = self.strategy_rules.calculate_net_unrealized_pnl(entry_price=Decimal(str(position.price)), current_price=current_price, total_quantity=Decimal(str(position.remaining_quantity)), buy_commission_usd=Decimal(str(position.commission_usd or '0')))
                            decision, reason, new_trail_percentage = self.strategy_rules.evaluate_smart_trailing_stop(position.to_dict(), net_unrealized_pnl, self.dynamic_params.parameters)
                            if decision == "ACTIVATE":
                                logger.info(f"🚀 {reason}")
                                self.state_manager.update_trade_smart_trailing_state(trade_id=position.trade_id, is_active=True, highest_profit=net_unrealized_pnl, activation_price=current_price)
                                position.is_smart_trailing_active = True
                                position.smart_trailing_highest_profit = net_unrealized_pnl
                                position.smart_trailing_activation_price = current_price
                            elif decision == "UPDATE_PEAK":
                                logger.info(f"📈 {reason}")
                                self.state_manager.update_trade_smart_trailing_state(trade_id=position.trade_id, is_active=True, highest_profit=net_unrealized_pnl, current_trail_percentage=new_trail_percentage)
                                position.smart_trailing_highest_profit = net_unrealized_pnl
                                if new_trail_percentage:
                                    position.current_trail_percentage = new_trail_percentage
                            elif decision == "DEACTIVATE":
                                logger.info(f"🔵 {reason}")
                                self.state_manager.update_trade_smart_trailing_state(
                                    trade_id=position.trade_id,
                                    is_active=False,
                                    highest_profit=Decimal('0'),
                                    activation_price=None,
                                    current_trail_percentage=None
                                )
                                position.is_smart_trailing_active = False
                                position.smart_trailing_highest_profit = Decimal('0')
                                position.smart_trailing_activation_price = None
                            elif decision == "SELL":
                                logger.info(f"✅ {reason}")
                                sell_candidates.append((position, "trailing_stop"))
                        if sell_candidates:
                            self._execute_sell_candidates(sell_candidates, current_price, base_asset, market_data)
                        self._evaluate_and_execute_buy(market_data, open_positions, current_params, current_regime, current_price)
                    else:
                        logger.info("Trading logic is paused while the bot is synchronizing.")
                    if current_time - last_status_update_time > 4:
                        total_portfolio_value = self.live_portfolio_manager.get_total_portfolio_value(current_price, force_recalculation=True)
                        all_prices = self.trader.get_all_prices()
                        wallet_balances = self.account_manager.get_all_account_balances(all_prices)
                        full_trade_history = self.state_manager.get_trade_history_for_run()
                        self._write_state_to_file(open_positions, current_price, wallet_balances, full_trade_history, total_portfolio_value)
                        self._update_status_file(market_data, current_params, open_positions, total_portfolio_value, current_regime)
                        last_status_update_time = current_time
                    logger.info("--- Cycle complete. Waiting 2 seconds...")
                    time.sleep(2)
                except Exception as e:
                    logger.critical(f"❌ Critical error in main loop: {e}", exc_info=True)
                    time.sleep(15)
        finally:
            self.shutdown()

    def _ensure_tui_directory_exists(self):
        """Ensures the .tui_files directory exists."""
        status_dir = ".tui_files"
        try:
            os.makedirs(status_dir, exist_ok=True)
        except OSError as e:
            logger.error(f"Error creating TUI directory '{status_dir}': {e}", exc_info=True)
            raise

    def _write_status_file_for_tui(self, status_data: dict):
        """
        Safely writes the status data to a file for the TUI to consume.
        Uses a temporary file and atomic move for safety.
        """
        try:
            self._ensure_tui_directory_exists()
            status_file_path = os.path.join(".tui_files", f".bot_status_{self.bot_name}.json")
            
            # Use a temporary file in the same directory to ensure atomic move
            with tempfile.NamedTemporaryFile(mode='w', delete=False, dir=".tui_files", prefix=f".bot_status_{self.bot_name}_", suffix=".tmp") as temp_f:
                json.dump(status_data, temp_f, default=str)
                temp_path = temp_f.name

            # shutil.move is more robust than os.rename across filesystems (common in Docker)
            shutil.move(temp_path, status_file_path)
            logger.info("Status file update complete.")
        except Exception as e:
            logger.error(f"Failed to write status file for TUI during update: {e}", exc_info=True)


    def _update_status_file(self, market_data, current_params, open_positions, total_portfolio_value, current_regime):
        """
        Gathers the bot's current state and triggers the write to the JSON file for the TUI.
        """
        logger.info("Starting status file update...")
        # 1. Update the status in the database (internal state)
        self.status_service.update_bot_status(
            bot_id=self.bot_name, mode=self.mode, reason=self.last_decision_reason,
            open_positions=len(open_positions), portfolio_value=total_portfolio_value,
            market_regime=current_regime, operating_mode=self.last_operating_mode,
            buy_target=calculate_buy_progress(market_data, current_params, self.last_difficulty_factor)[0],
            buy_progress=calculate_buy_progress(market_data, current_params, self.last_difficulty_factor)[1],
            cash_balance=self.live_portfolio_manager.cached_cash_balance,
            invested_value=self.live_portfolio_manager.cached_open_positions_value
        )
        # 2. Get the full, extended status for the TUI
        status_data = self.status_service.get_extended_status(self.mode, self.bot_name)

        # 3. Add portfolio history to the TUI data
        portfolio_history = self.db_manager.get_portfolio_history(self.bot_name)
        status_data['portfolio_history'] = [p.to_dict() for p in portfolio_history]

        # 4. Write the final data to the file
        self._write_status_file_for_tui(status_data)


    def _update_sync_status_file(self):
        """A lightweight status update for showing sync status in the TUI."""
        logger.info("Updating TUI with sync status...")
        try:
            self._ensure_tui_directory_exists()
            status_file_path = os.path.join(".tui_files", f".bot_status_{self.bot_name}.json")
            
            status_data = {}
            # Read existing data if possible to not overwrite everything
            if os.path.exists(status_file_path):
                try:
                    with open(status_file_path, "r") as f:
                        status_data = json.load(f)
                except (json.JSONDecodeError, IOError):
                    logger.warning(f"Could not read existing status file at {status_file_path}. A new one will be created.")

            # Override only the necessary fields for sync status
            if self.is_syncing:
                status_data['bot_status'] = "SYNCHRONIZING..."
                if 'buy_signal_status' not in status_data: status_data['buy_signal_status'] = {}
                status_data['buy_signal_status']['operating_mode'] = "SYNCHRONIZING..."
                status_data['buy_signal_status']['reason'] = "Performing state synchronization with the exchange."
            else:
                status_data['bot_status'] = "RUNNING"
                if 'buy_signal_status' in status_data:
                    status_data['buy_signal_status']['operating_mode'] = self.last_operating_mode
                    status_data['buy_signal_status']['reason'] = self.last_decision_reason

            # Write the updated data to the file
            self._write_status_file_for_tui(status_data)
        except Exception as e:
            logger.error(f"Failed to write sync status file for TUI: {e}", exc_info=True)

    def shutdown(self):
        logger.info("[SHUTDOWN] Initiating graceful shutdown...")
        if hasattr(self, 'status_service'):
            self.status_service.set_bot_stopped(self.bot_name)
        logger.info("[SHUTDOWN] Cleanup complete. Goodbye!")