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
        bucket_name = config_manager.get('INFLUXDB', f'bucket_{self.mode}')
        state_manager = StateManager(bucket_name)
        trader = Trader(mode=self.mode)
        strategy_rules = StrategyRules(config_manager)

        self.is_running = True
        logger.info(f"🚀 --- TRADING LOOP STARTED FOR SYMBOL {self.symbol} IN {self.mode.upper()} MODE --- 🚀")

        while self.is_running:
            try:
                current_price = self.market_data_provider.get_current_price(self.symbol)
                if not current_price:
                    logger.warning("Could not retrieve current price. Skipping cycle.")
                    time.sleep(10)
                    continue

                # 1. Check for potential sales
                open_positions = state_manager.get_open_positions()
                for position in open_positions:
                    # This is a placeholder for the actual sell logic, which will be more complex
                    if current_price >= position.get('entry_price', 0) * 1.02: # Simple 2% take profit
                        sell_result = trader.execute_sell(position)
                        if sell_result:
                            state_manager.close_trade(position['trade_id'], sell_result)

                # 2. Check for a potential buy
                last_buy_price = state_manager.get_last_purchase_price() # This method needs to be implemented in StateManager
                open_positions_count = state_manager.get_open_positions_count()

                buy_trigger_percentage = strategy_rules.get_next_buy_trigger(open_positions_count)

                if current_price <= last_buy_price * (1 - buy_trigger_percentage):
                    capital_allocated = state_manager.get_total_capital_allocated()
                    total_balance = trader.get_account_balance()
                    capital_allocated_percent = (capital_allocated / (total_balance + capital_allocated)) * 100
                    base_amount = float(config_manager.get('TRADING_STRATEGY', 'usd_per_trade'))

                    buy_amount_usdt = strategy_rules.get_next_buy_amount(capital_allocated_percent, base_amount)

                    buy_result = trader.execute_buy(buy_amount_usdt)
                    if buy_result:
                        state_manager.open_trade(buy_result)

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
