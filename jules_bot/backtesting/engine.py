import logging
import uuid
import pandas as pd
from jules_bot.core.mock_exchange import MockTrader
from jules_bot.database.database_manager import DatabaseManager
from jules_bot.database.data_manager import DataManager
from jules_bot.utils.config_manager import config_manager
from jules_bot.core_logic.strategy_rules import StrategyRules
from jules_bot.utils.logger import logger
from jules_bot.core.schemas import TradePoint
from jules_bot.research.feature_engineering import add_all_features

class Backtester:
    def __init__(self, days: int):
        self.days = days
        self.run_id = f"backtest_{uuid.uuid4()}"
        logger.info(f"Initializing new backtest run with ID: {self.run_id} for the last {self.days} days.")

        db_config = config_manager.get_db_config()
        db_config['bucket'] = config_manager.get('INFLUXDB', 'bucket_backtest')
        self.db_manager = DatabaseManager(config=db_config)
        self.data_manager = DataManager(self.db_manager, config_manager, logger)

        symbol = config_manager.get('APP', 'symbol')
        interval = config_manager.get('DATA', 'interval', fallback='1m')
        price_data = self.data_manager.get_price_history(
            symbol=symbol,
            interval=interval,
            start_date=f"-{self.days}d"
        )

        if price_data.empty:
            raise ValueError("No price data found for the specified period. Cannot run backtest.")

        logger.info("Calculating features for the entire backtest period...")
        self.feature_data = add_all_features(price_data, live_mode=False).dropna()
        logger.info("Feature calculation complete.")

        backtest_settings = config_manager.get_section('BACKTEST')
        self.mock_trader = MockTrader(
            initial_balance_usd=float(backtest_settings['initial_balance']),
            commission_fee_percent=float(backtest_settings['commission_fee']),
            symbol=symbol
        )

    def run(self):
        logger.info(f"--- Starting backtest run {self.run_id} ---")

        strategy_rules = StrategyRules(config_manager)
        symbol = config_manager.get('APP', 'symbol')
        strategy_name = config_manager.get('APP', 'strategy_name', fallback='default_strategy')

        open_positions = {}
        last_buy_price = float('inf')
        total_capital_allocated = 0.0

        for current_time, candle in self.feature_data.iterrows():
            self.mock_trader.set_current_time_and_price(current_time, candle['close'])
            current_price = candle['close']

            # 1. Check for potential sales
            for trade_id, position in list(open_positions.items()):
                target_price = position.get('sell_target_price', float('inf'))
                if current_price >= target_price:
                    logger.debug(f"Backtest: Sell condition met for {trade_id} at price {current_price}")

                    original_quantity = position['quantity']
                    sell_quantity = original_quantity * strategy_rules.rules.getfloat('sell_factor', 0.9)
                    hodl_asset_amount = original_quantity - sell_quantity

                    success, sell_result = self.mock_trader.execute_sell({'quantity': sell_quantity})
                    if success:
                        commission_usd = sell_result['commission']
                        realized_pnl_usd = (sell_result['price'] - position['price']) * sell_result['quantity'] - commission_usd
                        hodl_asset_value_at_sell = hodl_asset_amount * sell_result['price']
                        decision_context = candle.to_dict()

                        trade_point = TradePoint(
                            run_id=self.run_id, environment="backtest", strategy_name=strategy_name,
                            symbol=symbol, trade_id=trade_id, exchange="backtest_engine",
                            order_type="sell", price=sell_result['price'], quantity=sell_result['quantity'],
                            usd_value=sell_result['usd_value'], commission=commission_usd, commission_asset="USDT",
                            timestamp=current_time, decision_context=decision_context,
                            commission_usd=commission_usd, realized_pnl_usd=realized_pnl_usd,
                            hodl_asset_amount=hodl_asset_amount, hodl_asset_value_at_sell=hodl_asset_value_at_sell
                        )
                        self.db_manager.log_trade(trade_point)

                        total_capital_allocated -= position['usd_value']
                        del open_positions[trade_id]

            # 2. Check for a potential buy
            open_positions_count = len(open_positions)
            buy_trigger_percentage = strategy_rules.get_next_buy_trigger(open_positions_count)

            if current_price <= last_buy_price * (1 - buy_trigger_percentage):
                logger.info("Backtest: Buy condition met. Evaluating capital.")

                total_balance = self.mock_trader.get_account_balance()
                capital_allocated_percent = (total_capital_allocated / (total_balance + total_capital_allocated)) * 100 if (total_balance + total_capital_allocated) > 0 else 0
                base_amount = float(config_manager.get('TRADING_STRATEGY', 'usd_per_trade'))
                buy_amount_usdt = strategy_rules.get_next_buy_amount(capital_allocated_percent, base_amount)

                logger.debug(f"Backtest: Attempting to buy ${buy_amount_usdt}")
                success, buy_result = self.mock_trader.execute_buy(buy_amount_usdt)

                if success:
                    new_trade_id = str(uuid.uuid4())
                    buy_price = buy_result['price']

                    # Calculate sell target price
                    commission_rate = strategy_rules.rules.getfloat('commission_rate')
                    sell_factor = strategy_rules.rules.getfloat('sell_factor')
                    target_profit = strategy_rules.rules.getfloat('target_profit')
                    numerator = buy_price * (1 + commission_rate)
                    denominator = sell_factor * (1 - commission_rate)
                    break_even_price = numerator / denominator if denominator != 0 else float('inf')
                    sell_target_price = break_even_price * (1 + target_profit)

                    decision_context = candle.to_dict()
                    trade_point = TradePoint(
                        run_id=self.run_id, environment="backtest", strategy_name=strategy_name,
                        symbol=symbol, trade_id=new_trade_id, exchange="backtest_engine",
                        order_type="buy", price=buy_price, quantity=buy_result['quantity'],
                        usd_value=buy_result['usd_value'], commission=buy_result['commission'],
                        commission_asset="USDT", timestamp=current_time, decision_context=decision_context,
                        sell_target_price=sell_target_price
                    )
                    self.db_manager.log_trade(trade_point)

                    position_data = trade_point.to_dict()
                    position_data['sell_target_price'] = sell_target_price # Ensure it's in the dict for sell logic
                    open_positions[new_trade_id] = position_data
                    last_buy_price = buy_price
                    total_capital_allocated += buy_result['usd_value']

        self._generate_and_save_summary()
        logger.info(f"--- Backtest {self.run_id} finished ---")

    def _generate_and_save_summary(self):
        logger.info("--- Generating and saving backtest summary ---")

        all_trades_query = f'''
        from(bucket: "{self.db_manager.bucket}")
          |> range(start: 0)
          |> filter(fn: (r) => r._measurement == "trades")
          |> filter(fn: (r) => r.run_id == "{self.run_id}")
          |> pivot(rowKey:["_time"], columnKey: ["_field"], valueColumn: "_value")
        '''
        all_trades_df = self.db_manager.query_api.query_data_frame(all_trades_query)

        if isinstance(all_trades_df, list):
            all_trades_df = pd.concat(all_trades_df, ignore_index=True) if all_trades_df else pd.DataFrame()

        if all_trades_df.empty:
            logger.warning("No trades were executed in this backtest run.")
            total_pnl = 0
            num_trades = 0
        else:
            sell_trades = all_trades_df[all_trades_df['order_type'] == 'sell']
            total_pnl = sell_trades['realized_pnl_usd'].sum() if 'realized_pnl_usd' in sell_trades.columns else 0
            num_trades = len(sell_trades)

        initial_balance = self.mock_trader.initial_balance
        final_balance = self.mock_trader.get_account_balance()
        total_pnl_balance = final_balance - initial_balance
        total_pnl_percent = (total_pnl_balance / initial_balance) * 100 if initial_balance > 0 else 0

        logger.info("========== BACKTEST RESULTS ==========")
        logger.info(f" Backtest Run ID: {self.run_id}")
        if not self.feature_data.empty:
            start_time = self.feature_data.index[0]
            end_time = self.feature_data.index[-1]
            logger.info(f" Period: {start_time} to {end_time}")
        logger.info(f" Initial Balance: ${initial_balance:,.2f}")
        logger.info(f" Final Balance:   ${final_balance:,.2f}")
        logger.info(f" Total P&L (Cash): ${total_pnl_balance:,.2f} ({total_pnl_percent:.2f}%)")
        logger.info(f" Sum of Realized PnL (from trades): ${total_pnl:,.2f}")
        logger.info(f" Total Closed Trades (Sells): {num_trades}")
        logger.info("========================================")

# Add a to_dict method to TradePoint if it doesn't exist, for easy conversion
def trade_point_to_dict(self):
    from dataclasses import asdict
    return asdict(self)
TradePoint.to_dict = trade_point_to_dict
