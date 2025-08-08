import logging
import uuid
import pandas as pd
from jules_bot.core.mock_exchange import MockTrader
from jules_bot.database.database_manager import DatabaseManager
from jules_bot.database.data_manager import DataManager
from jules_bot.utils.config_manager import config_manager
from jules_bot.core_logic.state_manager import StateManager
from jules_bot.core_logic.strategy_rules import StrategyRules
from jules_bot.utils.logger import logger

class Backtester:
    def __init__(self, days: int):
        self.days = days
        self.backtest_id = f"backtest_{uuid.uuid4()}"
        logger.info(f"Initializing new backtest run with ID: {self.backtest_id} for the last {self.days} days.")

        # 1. Connect to the backtest database
        db_config = config_manager.get_section('INFLUXDB')
        db_config['bucket'] = config_manager.get('INFLUXDB', 'bucket_backtest')
        db_config['url'] = f"http://{db_config['host']}:{db_config['port']}"
        self.db_manager = DatabaseManager(config=db_config)
        self.data_manager = DataManager(self.db_manager, config_manager, logger) # Pass config and logger

        # Fetch price data using the new DataManager method
        symbol = config_manager.get('APP', 'symbol')
        interval = config_manager.get('DATA', 'interval', fallback='1m')
        price_data = self.data_manager.get_price_history(
            symbol=symbol,
            interval=interval,
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

        strategy_rules = StrategyRules(config_manager)
        symbol = config_manager.get('APP', 'symbol')
        strategy_name = config_manager.get('APP', 'strategy_name', fallback='default_strategy')

        open_positions = {} # Using a simple dict to track open positions in-memory for the backtest
        last_buy_price = float('inf')

        while self.mock_trader.advance_time():
            current_price_info = self.mock_trader.get_current_price_info()
            if current_price_info is None:
                continue

            current_price = current_price_info['price']
            current_time = current_price_info['time']

            # 1. Check for potential sales
            # Iterate over a copy of items, as we may modify the dict during iteration
            for trade_id, position in list(open_positions.items()):
                # The sell logic from the guide is based on a simple profit target.
                # A real strategy would be more complex. Here we simulate a 0.5% profit target.
                if current_price >= position['price'] * 1.005:
                    logger.debug(f"Backtest: Sell condition met for {trade_id} at price {current_price}")

                    # As per the guide: sell 90%, hold 10%
                    original_quantity = position['quantity']
                    sell_quantity = original_quantity * 0.9
                    held_quantity = original_quantity * 0.1

                    success, sell_result = self.mock_trader.execute_sell({'quantity': sell_quantity})
                    if success:
                        realized_pnl = (sell_result['price'] - position['price']) * sell_result['quantity'] - sell_result['commission']

                        trade_data = {
                            "mode": "backtest",
                            "strategy_name": strategy_name,
                            "symbol": symbol,
                            "trade_id": trade_id,
                            "exchange": "backtest_engine",
                            "order_type": "sell",
                            "price": sell_result['price'],
                            "quantity": sell_result['quantity'],
                            "usd_value": sell_result['usd_value'],
                            "commission": sell_result['commission'],
                            "commission_asset": "USDT",
                            "exchange_order_id": f"sim_{uuid.uuid4()}",
                            "realized_pnl": realized_pnl,
                            "held_quantity": held_quantity,
                            "timestamp": current_time,
                            "backtest_id": self.backtest_id # Add backtest_id for traceability
                        }
                        self.db_manager.log_trade(trade_data)
                        del open_positions[trade_id] # Position is now closed

            # 2. Check for a potential buy
            # Simplified buy logic: buy if price drops 2% from the last buy price.
            if not open_positions and current_price <= last_buy_price * 0.98:
                buy_amount_usdt = float(config_manager.get('BACKTEST', 'usd_per_trade', fallback=100))

                logger.debug(f"Backtest: Buy condition met. Attempting to buy ${buy_amount_usdt}")
                success, buy_result = self.mock_trader.execute_buy(buy_amount_usdt)

                if success:
                    new_trade_id = str(uuid.uuid4())
                    buy_price = buy_result['price']

                    trade_data = {
                        "mode": "backtest",
                        "strategy_name": strategy_name,
                        "symbol": symbol,
                        "trade_id": new_trade_id,
                        "exchange": "backtest_engine",
                        "order_type": "buy",
                        "price": buy_price,
                        "quantity": buy_result['quantity'],
                        "usd_value": buy_result['usd_value'],
                        "commission": buy_result['commission'],
                        "commission_asset": "USDT",
                        "exchange_order_id": f"sim_{uuid.uuid4()}",
                        "timestamp": current_time,
                        "backtest_id": self.backtest_id # Add backtest_id for traceability
                    }
                    self.db_manager.log_trade(trade_data)

                    # Store position details for later
                    open_positions[new_trade_id] = trade_data
                    last_buy_price = buy_price

        self._generate_and_save_summary()
        logger.info(f"--- Backtest {self.backtest_id} finished ---")

    def _generate_and_save_summary(self):
        logger.info("--- Generating and saving backtest summary ---")

        # Query all trades for this specific backtest run
        all_trades_query = f'''
        from(bucket: "{self.db_manager.bucket}")
          |> range(start: 0)
          |> filter(fn: (r) => r._measurement == "trades")
          |> filter(fn: (r) => r.backtest_id == "{self.backtest_id}")
          |> pivot(rowKey:["_time"], columnKey: ["_field"], valueColumn: "_value")
        '''
        all_trades = self.db_manager.query_api.query_data_frame(all_trades_query)

        if isinstance(all_trades, list):
            all_trades = pd.concat(all_trades, ignore_index=True) if all_trades else pd.DataFrame()

        if all_trades.empty:
            logger.warning("No trades were executed in this backtest run.")
            total_pnl = 0
            num_trades = 0
        else:
            # Calculate PnL from the 'sell' records
            sell_trades = all_trades[all_trades['order_type'] == 'sell']
            total_pnl = sell_trades['realized_pnl'].sum()
            num_trades = len(sell_trades)

        initial_balance = self.mock_trader.initial_balance
        final_balance = self.mock_trader.get_account_balance() # This includes cash + value of any held assets

        # The PnL from the perspective of the starting cash vs ending cash
        total_pnl_balance = final_balance - initial_balance
        total_pnl_percent = (total_pnl_balance / initial_balance) * 100 if initial_balance > 0 else 0

        logger.info("========== BACKTEST RESULTS ==========")
        logger.info(f" Backtest ID: {self.backtest_id}")
        if not self.mock_trader.historical_data.empty:
            start_time = self.mock_trader.historical_data.index[0]
            end_time = self.mock_trader.historical_data.index[-1]
            logger.info(f" Period: {start_time} to {end_time}")
        logger.info(f" Initial Balance: ${initial_balance:,.2f}")
        logger.info(f" Final Balance:   ${final_balance:,.2f}")
        logger.info(f" Total P&L (Cash): ${total_pnl_balance:,.2f} ({total_pnl_percent:.2f}%)")
        logger.info(f" Sum of Realized PnL (from trades): ${total_pnl:,.2f}")
        logger.info(f" Total Closed Trades (Sells): {num_trades}")
        logger.info("========================================")
