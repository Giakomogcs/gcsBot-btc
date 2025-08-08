import logging
import uuid
from jules_bot.core.mock_exchange import MockTrader
from jules_bot.core.market_data_provider import MarketDataProvider
from jules_bot.database.database_manager import DatabaseManager
from jules_bot.utils.config_manager import config_manager
from jules_bot.core_logic.state_manager import StateManager
from jules_bot.core_logic.strategy_rules import StrategyRules

class Backtester:
    def __init__(self, historical_data_path: str):
        self.historical_data_path = historical_data_path
        self.backtest_id = f"backtest_{uuid.uuid4()}"
        logging.info(f"Initializing new backtest run with ID: {self.backtest_id}")

        market_db_config = config_manager.get_section('INFLUXDB')
        market_db_config['bucket'] = config_manager.get('INFLUXDB', 'bucket_prices')
        market_db_config['url'] = f"http://{market_db_config['host']}:{market_db_config['port']}"
        market_db_manager = DatabaseManager(config=market_db_config)
        data_provider = MarketDataProvider(market_db_manager)
        all_data = data_provider.get_historical_data(symbol="BTC/USD", start="-1y")

        backtest_settings = config_manager.get_section('BACKTEST')
        self.mock_trader = MockTrader(
            historical_data=all_data,
            initial_balance_usd=float(backtest_settings['initial_balance']),
            commission_fee_percent=float(backtest_settings['commission_fee'])
        )

    def run(self):
        """The main backtesting loop."""
        logging.info(f"Starting backtest run {self.backtest_id}...")

        state_manager = StateManager(config_manager.get('INFLUXDB', 'bucket_backtest'))
        strategy_rules = StrategyRules(config_manager)

        while self.mock_trader.advance_time():
            current_price = self.mock_trader.get_current_price(config_manager.get('APP', 'symbol'))

            # 1. Check for potential sales
            open_positions = state_manager.get_open_positions()
            for position in open_positions:
                if current_price >= position.get('entry_price', 0) * 1.02: # Simple 2% take profit
                    success, sell_result = self.mock_trader.execute_sell(position)
                    if success:
                        state_manager.close_trade(position['trade_id'], sell_result)

            # 2. Check for a potential buy
            last_buy_price = state_manager.get_last_purchase_price() # This method needs to be implemented in StateManager
            open_positions_count = state_manager.get_open_positions_count()

            buy_trigger_percentage = strategy_rules.get_next_buy_trigger(open_positions_count)

            if current_price <= last_buy_price * (1 - buy_trigger_percentage):
                capital_allocated = state_manager.get_total_capital_allocated()
                total_balance = self.mock_trader.get_account_balance()
                capital_allocated_percent = (capital_allocated / (total_balance + capital_allocated)) * 100
                base_amount = float(config_manager.get('TRADING_STRATEGY', 'usd_per_trade'))

                buy_amount_usdt = strategy_rules.get_next_buy_amount(capital_allocated_percent, base_amount)

                success, buy_result = self.mock_trader.execute_buy(buy_amount_usdt)
                if success:
                    state_manager.open_trade(buy_result)

        self._generate_and_save_summary(state_manager)
        logging.info(f"Backtest {self.backtest_id} finished.")

    def _generate_and_save_summary(self, state_manager):
        logging.info("Generating and saving backtest summary...")
        all_trades = state_manager.db_manager.get_all_trades_in_range()
        closed_trades = all_trades[all_trades['status'] == 'CLOSED']

        initial_balance = self.mock_trader.initial_balance
        final_balance = self.mock_trader.usd_balance
        pnl = final_balance - initial_balance
        pnl_percent = (pnl / initial_balance) * 100 if initial_balance > 0 else 0

        logging.info("========== BACKTEST RESULTS ==========")
        logging.info(f"Initial Balance: ${initial_balance:,.2f}")
        logging.info(f"Final Balance:   ${final_balance:,.2f}")
        logging.info(f"Total P&L: ${pnl:,.2f} ({pnl_percent:.2f}%)")
        logging.info(f"Total Closed Trades: {len(closed_trades)}")
        logging.info("========================================")
