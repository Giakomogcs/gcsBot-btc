import logging
import uuid
import pandas as pd
from jules_bot.core.mock_exchange import MockTrader
from jules_bot.database.database_manager import DatabaseManager
from jules_bot.utils.config_manager import config_manager
from jules_bot.core_logic.state_manager import StateManager
from jules_bot.core_logic.strategy_rules import StrategyRules
from jules_bot.utils.logger import logger

class Backtester:
    def __init__(self, days: int):
        self.days = days
        self.backtest_id = f"backtest_{uuid.uuid4()}"
        logger.info(f"Initializing new backtest run with ID: {self.backtest_id} for the last {self.days} days.")

        # 1. Connect to the backtest database to get price data
        db_config = config_manager.get_section('INFLUXDB')
        db_config['bucket'] = config_manager.get('INFLUXDB', 'bucket_backtest')
        db_config['url'] = f"http://{db_config['host']}:{db_config['port']}"
        self.db_manager = DatabaseManager(config=db_config)

        price_data = self.db_manager.get_price_data(
            measurement="btc_prices",
            start_date=f"-{self.days}d"
        )

        if price_data.empty:
            raise ValueError("No price data found in the backtest bucket for the specified period. Cannot run backtest.")

        # 2. Initialize the MockTrader with the historical data
        backtest_settings = config_manager.get_section('BACKTEST')
        self.mock_trader = MockTrader(
            historical_data=price_data,
            initial_balance_usd=float(backtest_settings['initial_balance']),
            commission_fee_percent=float(backtest_settings['commission_fee'])
        )

    def run(self):
        """The main backtesting loop, using the same logic as the live trading bot."""
        logger.info(f"--- Starting backtest run {self.backtest_id} ---")

        # Use a separate StateManager for the backtest results, pointing to the same backtest bucket
        state_manager = StateManager(
            bucket_name=config_manager.get('INFLUXDB', 'bucket_backtest'),
            bot_id=self.backtest_id
        )
        strategy_rules = StrategyRules(config_manager)
        symbol = config_manager.get('APP', 'symbol')

        # Clear any previous trade data for this backtest ID to ensure a clean run
        logger.info(f"Clearing previous trade data for bot_id '{self.backtest_id}'...")
        state_manager.db_manager.clear_measurement(f'trades_bot_id="{self.backtest_id}"')

        while self.mock_trader.advance_time():
            current_price = self.mock_trader.get_current_price()
            if not current_price:
                continue

            # 1. Check for potential sales (using the new logic)
            open_positions = state_manager.get_open_positions()
            for position in open_positions:
                trade_id = position.get('trade_id')
                target_price = position.get('sell_target_price', float('inf'))
                if current_price >= target_price:
                    logger.debug(f"Backtest: Sell condition met for {trade_id} at price {current_price}")
                    success, sell_result = self.mock_trader.execute_sell(position)
                    if success:
                        state_manager.close_position(trade_id, sell_result)

            # 2. Check for a potential buy (using the new logic)
            last_buy_price = state_manager.get_last_purchase_price()
            open_positions_count = state_manager.get_open_positions_count()
            buy_trigger_percentage = strategy_rules.get_next_buy_trigger(open_positions_count)

            if current_price <= last_buy_price * (1 - buy_trigger_percentage):
                capital_allocated = state_manager.get_total_capital_allocated()
                total_balance = self.mock_trader.get_account_balance()
                capital_allocated_percent = (capital_allocated / (total_balance + capital_allocated)) * 100 if (total_balance + capital_allocated) > 0 else 0
                base_amount = float(config_manager.get('TRADING_STRATEGY', 'usd_per_trade'))
                buy_amount_usdt = strategy_rules.get_next_buy_amount(capital_allocated_percent, base_amount)

                logger.debug(f"Backtest: Buy condition met. Attempting to buy ${buy_amount_usdt}")
                success, buy_result = self.mock_trader.execute_buy(buy_amount_usdt)
                if success:
                    buy_result['symbol'] = symbol
                    state_manager.create_new_position(buy_result)

        self._generate_and_save_summary(state_manager)
        logger.info(f"--- Backtest {self.backtest_id} finished ---")

    def _generate_and_save_summary(self, state_manager):
        logger.info("--- Generating and saving backtest summary ---")

        # We need to fetch trades specifically for this backtest run
        all_trades_query = f'''
        from(bucket: "{state_manager.db_manager.bucket}")
          |> range(start: 0)
          |> filter(fn: (r) => r._measurement == "trades" and r.bot_id == "{self.backtest_id}")
          |> pivot(rowKey:["_time"], columnKey: ["_field"], valueColumn: "_value")
        '''
        all_trades = state_manager.db_manager.query_api.query_data_frame(all_trades_query)

        if isinstance(all_trades, list):
            all_trades = pd.concat(all_trades, ignore_index=True) if all_trades else pd.DataFrame()

        if all_trades.empty:
            logger.warning("No trades were executed in this backtest run.")
            closed_trades = []
        else:
            closed_trades = all_trades[all_trades['status'] == 'CLOSED']

        initial_balance = self.mock_trader.initial_balance
        final_balance = self.mock_trader.get_account_balance()
        pnl = final_balance - initial_balance
        pnl_percent = (pnl / initial_balance) * 100 if initial_balance > 0 else 0

        logger.info("========== BACKTEST RESULTS ==========")
        logger.info(f" Backtest ID: {self.backtest_id}")
        if not self.mock_trader.historical_data.empty:
            start_time = self.mock_trader.historical_data.index[0]
            end_time = self.mock_trader.historical_data.index[-1]
            logger.info(f" Period: {start_time} to {end_time}")
        logger.info(f" Initial Balance: ${initial_balance:,.2f}")
        logger.info(f" Final Balance:   ${final_balance:,.2f}")
        logger.info(f" Total P&L: ${pnl:,.2f} ({pnl_percent:.2f}%)")
        logger.info(f" Total Closed Trades: {len(closed_trades)}")
        logger.info("========================================")
