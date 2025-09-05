import time
from typing import Optional
import uuid
import json
import os
import tempfile
import threading
import uvicorn
from fastapi import FastAPI
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
from jules_bot.utils.helpers import _calculate_progress_pct, calculate_buy_progress
from jules_bot.bot.api import router as api_router
from jules_bot.bot.unified_logic import UnifiedTradingLogic

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
        self.capital_manager = CapitalManager(config_manager, self.strategy_rules, self.db_manager)

        equity_recalc_interval = int(config_manager.get('APP', 'equity_recalculation_interval', fallback=300))
        quote_asset = "USDT"
        self.live_portfolio_manager = LivePortfolioManager(self.trader, self.state_manager, self.db_manager, quote_asset, equity_recalc_interval)

        self.dynamic_params = DynamicParameters(config_manager)
        self.sa_instance = SituationalAwareness()

        # Instantiate the unified logic engine
        self.unified_logic = UnifiedTradingLogic(
            bot_id=self.run_id,
            mode=self.mode,
            trader=self.trader,
            state_manager=self.state_manager,
            capital_manager=self.capital_manager,
            strategy_rules=self.strategy_rules,
            dynamic_params=self.dynamic_params,
            sa_instance=self.sa_instance,
            portfolio_manager=self.live_portfolio_manager,
            db_manager=self.db_manager,
            account_manager=self.account_manager
        )

        self.last_decision_reason = "Initializing..."
        self.last_operating_mode = "STARTUP"
        self.last_difficulty_factor = Decimal("0.0")

        # API Setup
        self.api_app = FastAPI(title=f"Jules Bot API - {self.bot_name}")
        self.api_app.state.bot = self  # Make bot instance available to endpoints
        self.api_app.include_router(api_router, prefix="/api")
        self.api_port = int(os.getenv('API_PORT', '8766'))

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
        quantity_to_sell = Decimal(str(position.quantity)) * (percentage_decimal / Decimal("100"))

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

        # Start API server in a background thread
        uvicorn_config = uvicorn.Config(self.api_app, host="0.0.0.0", port=self.api_port, log_level="info")
        api_thread = threading.Thread(target=uvicorn.Server(config=uvicorn_config).run, daemon=True)
        api_thread.start()
        logger.info(f"🚀 --- TRADING BOT STARTED (API on port {self.api_port}) --- BOT NAME: {self.bot_name} --- RUN ID: {self.run_id} --- SYMBOL: {self.symbol} --- MODE: {self.mode.upper()} --- 🚀")

        try:
            while self.is_running:
                try:
                    self._check_and_handle_refresh_signal()
                    
                    features_df = self.feature_calculator.get_features_dataframe()
                    
                    # Run the unified trading cycle
                    cycle_results = self.unified_logic.run_trading_cycle(features_df)

                    # Unpack results. If None, it means the cycle was skipped.
                    if cycle_results:
                        reason, op_mode, diff_factor, regime, portfolio_val = cycle_results
                        self.last_decision_reason = reason
                        self.last_operating_mode = op_mode
                        self.last_difficulty_factor = diff_factor
                        
                        # The unified logic now handles its own state, but the bot needs to know the outcome for status updates.
                        # Persist the latest status to the database for the TUI
                        self.status_service.update_bot_status(
                            bot_id=self.bot_name, mode=self.mode, reason=reason,
                            open_positions=len(self.state_manager.get_open_positions()),
                            portfolio_value=portfolio_val,
                            market_regime=regime,
                            operating_mode=op_mode,
                            buy_target=Decimal('0'), # This needs to be calculated or passed back
                            buy_progress=Decimal('0') # This also needs to be passed back
                        )
                        self._update_status_file()

                    logger.info("--- Cycle complete. Waiting 5 seconds...")
                    time.sleep(5)

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

            # 3. Get latest regime and parameters
            current_regime = -1
            if self.sa_instance:
                regime_df = self.sa_instance.transform(features_df)
                if not regime_df.empty:
                    current_regime = int(regime_df['market_regime'].iloc[-1])
            self.dynamic_params.update_parameters(current_regime)
            current_params = self.dynamic_params.parameters

            # 4. Use the stored decision from the main loop for consistency
            reason = self.last_decision_reason
            operating_mode = self.last_operating_mode

            # 5. Calculate buy progress using the same difficulty factor
            buy_target, buy_progress = calculate_buy_progress(market_data, current_params, self.last_difficulty_factor)

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