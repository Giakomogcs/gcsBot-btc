import time
from jules_bot.utils.logger import logger
from jules_bot.utils.config_manager import config_manager
from jules_bot.core_logic.state_manager import StateManager
from jules_bot.core_logic.trader import Trader
from jules_bot.core_logic.strategy_rules import StrategyRules
from jules_bot.core.market_data_provider import MarketDataProvider

class TradingBot:
    """
    The maestro that orquestrates all the components of the bot.
    """

    def __init__(self,
                 mode: str,
                 bot_id: str,
                 market_data_provider: MarketDataProvider):

        self.mode = mode
        self.bot_id = bot_id
        self.is_running = True
        self.market_data_provider = market_data_provider
        self.symbol = config_manager.get('APP', 'symbol')

    def run(self):
        """
        The main loop for TRADING and TEST.
        """
        if self.mode not in ['trade', 'test']:
            logger.error(f"The 'run' method cannot be called in '{self.mode}' mode. Use 'run_backtest'.")
            return

        # Instantiate core components
        if self.mode == 'trade':
            bucket_key = 'bucket_live'
        elif self.mode == 'test':
            bucket_key = 'bucket_testnet'
        else:
            logger.error(f"Invalid mode '{self.mode}' for determining bucket.")
            return

        bucket_name = config_manager.get('INFLUXDB', bucket_key)
        if not bucket_name:
            logger.error(f"Could not find bucket configuration for key '{bucket_key}' in config.ini")
            return

        state_manager = StateManager(bucket_name, self.bot_id)
        trader = Trader(mode=self.mode)
        strategy_rules = StrategyRules(config_manager)

        if not trader.is_ready:
            logger.critical("Trader could not be initialized. Shutting down bot.")
            return

        self.is_running = True
        logger.info(f"🚀 --- TRADING LOOP STARTED FOR SYMBOL {self.symbol} IN {self.mode.upper()} MODE --- 🚀")

        while self.is_running:
            try:
                current_price = trader.get_current_price(self.symbol)
                if current_price is None:
                    logger.warning("Could not retrieve current price. Skipping cycle.")
                    time.sleep(10)
                    continue

                # 1. Check for potential sales (Read -> Act -> Update State)
                logger.debug("--- SELL CYCLE START ---")
                logger.info("[Read] Fetching open positions.")
                open_positions = state_manager.get_open_positions()
                logger.info(f"Found {len(open_positions)} open position(s).")

                for position in open_positions:
                    trade_id = position.get('trade_id')
                    target_price = position.get('sell_target_price', float('inf'))
                    logger.debug(f"Checking position {trade_id}: current_price={current_price}, target_price={target_price}")

                    if current_price >= target_price:
                        logger.info(f"[Act] Sell condition met for position {trade_id}. Executing sell.")
                        sell_result = trader.execute_sell(position)

                        if sell_result:
                            logger.info(f"[Update State] Sell successful for {trade_id}. Closing position in database.")
                            state_manager.close_position(trade_id, sell_result)
                            logger.info(f"Position {trade_id} successfully closed.")
                        else:
                            logger.error(f"Sell execution failed for position {trade_id}. State remains OPEN.")
                logger.debug("--- SELL CYCLE END ---")

                # 2. Check for a potential buy
                logger.debug("--- BUY CYCLE START ---")
                last_buy_price = state_manager.get_last_purchase_price()
                open_positions_count = state_manager.get_open_positions_count()

                buy_trigger_percentage = strategy_rules.get_next_buy_trigger(open_positions_count)

                if current_price <= last_buy_price * (1 - buy_trigger_percentage):
                    logger.info("Buy condition met. Evaluating capital for new trade.")
                    capital_allocated = state_manager.get_total_capital_allocated()
                    total_balance = trader.get_account_balance()

                    # Avoid division by zero if total balance is 0
                    if total_balance + capital_allocated == 0:
                        capital_allocated_percent = 0
                    else:
                        capital_allocated_percent = (capital_allocated / (total_balance + capital_allocated)) * 100

                    base_amount = float(config_manager.get('TRADING_STRATEGY', 'usd_per_trade'))
                    buy_amount_usdt = strategy_rules.get_next_buy_amount(capital_allocated_percent, base_amount)

                    logger.info(f"Executing buy for ${buy_amount_usdt} USD.")
                    buy_result = trader.execute_buy(buy_amount_usdt)
                    if buy_result:
                        logger.info("Buy successful. Creating new position with calculated sell target.")
                        state_manager.create_new_position(buy_result)
                logger.debug("--- BUY CYCLE END ---")

                logger.info("--- Cycle complete. Waiting 10 seconds... ---")
                time.sleep(10)

            except KeyboardInterrupt:
                logger.info("\n[SHUTDOWN] Ctrl+C detected. Stopping main loop...")
                self.is_running = False
            except Exception as e:
                logger.critical(f"❌ A critical error occurred in the main loop: {e}", exc_info=True)
                time.sleep(300)

    def shutdown(self):
        """Handles all cleanup operations to ensure a clean exit."""
        print("\n[SHUTDOWN] Initiating graceful shutdown procedure...")
        # In a real application, you would close connections here
        print("[SHUTDOWN] Cleanup complete. Goodbye!")
