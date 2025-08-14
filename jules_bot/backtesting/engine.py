import logging
import uuid
import pandas as pd
from jules_bot.core.mock_exchange import MockTrader
from jules_bot.database.postgres_manager import PostgresManager
from jules_bot.utils.config_manager import config_manager
from jules_bot.core_logic.strategy_rules import StrategyRules
from jules_bot.utils.logger import logger
from jules_bot.core.schemas import TradePoint
from jules_bot.research.feature_engineering import add_all_features
from jules_bot.services.trade_logger import TradeLogger

class Backtester:
    def __init__(self, db_manager: PostgresManager, days: int = None, start_date: str = None, end_date: str = None):
        self.run_id = f"backtest_{uuid.uuid4()}"
        self.db_manager = db_manager
        
        log_msg = ""
        if days:
            self.start_date_str = f"-{days}d"
            self.end_date_str = "now()"
            log_msg = f"Initializing new backtest run with ID: {self.run_id} for the last {days} days."
        elif start_date and end_date:
            # Format dates to RFC3339 format for InfluxDB, which is timezone-aware
            self.start_date_str = f"{start_date}T00:00:00Z"
            self.end_date_str = f"{end_date}T23:59:59Z"
            log_msg = f"Initializing new backtest run with ID: {self.run_id} from {start_date} to {end_date}."
        else:
            raise ValueError("Backtester must be initialized with either 'days' or both 'start_date' and 'end_date'.")

        logger.info(log_msg)

        self.trade_logger = TradeLogger(mode='backtest', db_manager=self.db_manager)

        symbol = config_manager.get('APP', 'symbol')
        
        price_data = self.db_manager.get_price_data(
            measurement=symbol,
            start_date=self.start_date_str,
            end_date=self.end_date_str
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
        portfolio_history = []

        for current_time, candle in self.feature_data.iterrows():
            self.mock_trader.set_current_time_and_price(current_time, candle['close'])
            current_price = candle['close']

            cash_balance = self.mock_trader.get_account_balance()
            crypto_balance_in_usd = self.mock_trader.get_crypto_balance_in_usd()
            total_portfolio_value = cash_balance + crypto_balance_in_usd
            portfolio_history.append(total_portfolio_value)

            # 1. Check for potential sales
            for trade_id, position in list(open_positions.items()):
                target_price = position.get('sell_target_price', float('inf'))
                if current_price >= target_price:
                    logger.debug(f"Backtest: Sell condition met for {trade_id} at price {current_price}")

                    original_quantity = position['quantity']
                    sell_quantity = original_quantity * float(strategy_rules.rules.get('sell_factor', 0.9))
                    hodl_asset_amount = original_quantity - sell_quantity

                    success, sell_result = self.mock_trader.execute_sell({'quantity': sell_quantity})
                    if success:
                        # --- CORRECTED PNL CALCULATION ---
                        buy_price = position['price']
                        sell_price = sell_result['price']

                        # Note: The mock_trader uses a 'commission_fee' from the [BACKTEST] section,
                        # but for consistency in PnL calculation, we use the same commission_rate
                        # as the live bot from [STRATEGY_RULES].
                        commission_rate = float(strategy_rules.rules.get('commission_rate'))

                        realized_pnl_usd = ((sell_price * (1 - commission_rate)) - (buy_price * (1 + commission_rate))) * sell_result['quantity']
                        # --- END CORRECTED PNL CALCULATION ---

                        commission_usd = sell_result['commission'] # This is the actual commission charged by mock_trader
                        hodl_asset_value_at_sell = hodl_asset_amount * sell_result['price']

                        decision_context = candle.to_dict()
                        decision_context.pop('symbol', None)

                        trade_data = {
                            'run_id': self.run_id,
                            'strategy_name': strategy_name,
                            'symbol': symbol,
                            'trade_id': trade_id,
                            'exchange': "backtest_engine",
                            'order_type': "sell",
                            'status': "CLOSED",
                            'price': sell_result['price'],
                            'quantity': sell_result['quantity'],
                            'usd_value': sell_result['usd_value'],
                            'commission': commission_usd,
                            'commission_asset': "USDT",
                            'timestamp': current_time,
                            'decision_context': decision_context,
                            'commission_usd': commission_usd,
                            'realized_pnl_usd': realized_pnl_usd,
                            'hodl_asset_amount': hodl_asset_amount,
                            'hodl_asset_value_at_sell': hodl_asset_value_at_sell
                        }
                        # Use the new update_trade method for sells
                        self.trade_logger.update_trade(trade_data)

                        logger.info(f"SELL EXECUTED: TradeID: {trade_id} | "
                                    f"Buy Price: ${position['price']:,.2f} | "
                                    f"Sell Price: ${sell_result['price']:,.2f} | "
                                    f"Realized PnL: ${realized_pnl_usd:,.2f} | "
                                    f"HODL Amount: {hodl_asset_amount:.8f} BTC")

                        # --- START TREASURY LOGIC ---
                        # Mirror the live environment's logic by creating a new 'TREASURY' record
                        # for the amount that was held back from the sale.
                        if hodl_asset_amount > 1e-8: # Use a small tolerance for floating point
                            treasury_trade_id = str(uuid.uuid4())
                            buy_price = position['price']
                            treasury_usd_value = hodl_asset_amount * buy_price

                            treasury_data = {
                                'run_id': self.run_id,
                                'environment': 'backtest',
                                'strategy_name': strategy_name,
                                'symbol': symbol,
                                'trade_id': treasury_trade_id,
                                'exchange': "backtest_engine",
                                'status': 'TREASURY',
                                'order_type': 'buy', # Represents an asset we are holding
                                'price': buy_price,
                                'quantity': hodl_asset_amount,
                                'usd_value': treasury_usd_value,
                                'timestamp': current_time,
                                'decision_context': {
                                    'source': 'treasury',
                                    'original_trade_id': trade_id
                                }
                            }
                            self.trade_logger.log_trade(treasury_data)
                            logger.info(f"TREASURY CREATED: TradeID: {treasury_trade_id} | "
                                        f"Quantity: {hodl_asset_amount:.8f} BTC | "
                                        f"Value at cost: ${treasury_usd_value:,.2f}")
                        # --- END TREASURY LOGIC ---

                        total_capital_allocated -= position['usd_value']
                        del open_positions[trade_id]

            # 2. Check for a potential buy (New "Adaptive Momentum Grid" Strategy)
            open_positions_count = len(open_positions)
            max_open_positions = int(config_manager.get('STRATEGY_RULES', 'max_open_positions', fallback=20))

            if open_positions_count < max_open_positions:
                market_data = candle.to_dict()
                should_buy, regime, reason = strategy_rules.evaluate_buy_signal(market_data, open_positions_count)

                if should_buy:
                    available_balance = self.mock_trader.get_account_balance()
                    buy_amount_usdt = strategy_rules.get_next_buy_amount(available_balance)
                    min_trade_size = float(config_manager.get('TRADING_STRATEGY', 'min_trade_size_usdt', fallback=10.0))

                    if available_balance > 10 and buy_amount_usdt > min_trade_size:
                        logger.debug(f"Backtest: {reason}. Attempting to buy ${buy_amount_usdt:.2f}")
                        success, buy_result = self.mock_trader.execute_buy(buy_amount_usdt)

                        if success:
                            new_trade_id = str(uuid.uuid4())
                            buy_price = buy_result['price']
                            sell_target_price = strategy_rules.calculate_sell_target_price(buy_price)

                            # Enhanced data logging
                            decision_context = {
                                "market_regime": regime,
                                "buy_trigger_reason": reason,
                                "ema_100_value": market_data.get('ema_100'),
                                "ema_20_value": market_data.get('ema_20'),
                                "lower_bollinger_band": market_data.get('bbl_20_2_0'),
                                "regime_strength": None # Placeholder as per implementation
                            }

                            trade_data = {
                                'run_id': self.run_id,
                                'strategy_name': strategy_name,
                                'symbol': symbol,
                                'trade_id': new_trade_id,
                                'exchange': "backtest_engine",
                                'order_type': "buy",
                                'status': "OPEN",
                                'price': buy_price,
                                'quantity': buy_result['quantity'],
                                'usd_value': buy_result['usd_value'],
                                'commission': buy_result['commission'],
                                'commission_asset': "USDT",
                                'timestamp': current_time,
                                'decision_context': decision_context,
                                'sell_target_price': sell_target_price
                            }
                            self.trade_logger.log_trade(trade_data)

                            position_data = {
                                'price': buy_price,
                                'quantity': buy_result['quantity'],
                                'usd_value': buy_result['usd_value'],
                                'sell_target_price': sell_target_price
                            }
                            open_positions[new_trade_id] = position_data
                            total_capital_allocated += buy_result['usd_value']

        self._generate_and_save_summary(open_positions, portfolio_history)
        logger.info(f"--- Backtest {self.run_id} finished ---")

    def _generate_and_save_summary(self, open_positions: dict, portfolio_history: list):
        logger.info("--- Generating and saving backtest summary ---")

        # Fetch trades specifically for this backtest run
        all_trades_for_run = self.db_manager.get_trades_by_run_id(self.run_id)
        all_trades_df = pd.DataFrame([t.to_dict() for t in all_trades_for_run])

        if all_trades_df.empty:
            logger.warning("No trades were executed in this backtest run.")
            num_buy_trades = 0
            num_sell_trades = 0
            total_realized_pnl = 0.0
            total_fees_usd = 0.0
            win_rate = 0.0
            payoff_ratio = 0.0
            winning_trades_df = pd.DataFrame()
            losing_trades_df = pd.DataFrame()
        else:
            num_buy_trades = len(all_trades_df[all_trades_df['order_type'] == 'buy'])
            sell_trades = all_trades_df[all_trades_df['status'] == 'CLOSED']
            num_sell_trades = len(sell_trades)
            total_realized_pnl = sell_trades['realized_pnl_usd'].sum() if 'realized_pnl_usd' in sell_trades.columns else 0.0
            total_fees_usd = all_trades_df['commission_usd'].sum() if 'commission_usd' in all_trades_df.columns else 0.0

            winning_trades_df = sell_trades[sell_trades['realized_pnl_usd'] > 0]
            losing_trades_df = sell_trades[sell_trades['realized_pnl_usd'] <= 0]

            if num_sell_trades > 0:
                win_rate = (len(winning_trades_df) / num_sell_trades) * 100
            else:
                win_rate = 0.0

            if len(losing_trades_df) > 0 and losing_trades_df['realized_pnl_usd'].sum() != 0:
                avg_gain = winning_trades_df['realized_pnl_usd'].mean() if len(winning_trades_df) > 0 else 0
                avg_loss = abs(losing_trades_df['realized_pnl_usd'].mean()) if len(losing_trades_df) > 0 else 0
                payoff_ratio = avg_gain / avg_loss if avg_loss > 0 else float('inf')
            else:
                payoff_ratio = float('inf')

        initial_balance = self.mock_trader.initial_balance
        final_balance = self.mock_trader.get_total_portfolio_value()
        
        unrealized_pnl = 0.0
        if open_positions:
            current_price = self.mock_trader.get_current_price()
            for trade_id, position in open_positions.items():
                unrealized_pnl += (current_price * position['quantity']) - position['usd_value']

        total_pnl_balance = final_balance - initial_balance
        total_pnl_percent = (total_pnl_balance / initial_balance) * 100 if initial_balance > 0 else 0

        max_drawdown = 0.0
        peak = -float('inf')
        if portfolio_history:
            for value in portfolio_history:
                if value > peak:
                    peak = value
                drawdown = (peak - value) / peak if peak > 0 else 0
                if drawdown > max_drawdown:
                    max_drawdown = drawdown

        logger.info("========== BACKTEST RESULTS ==========")
        logger.info(f" Backtest Run ID: {self.run_id}")
        if not self.feature_data.empty:
            start_time = self.feature_data.index[0]
            end_time = self.feature_data.index[-1]
            logger.info(f" Period: {start_time.date()} to {end_time.date()}")
        logger.info(f" Initial Balance: ${initial_balance:,.2f}")
        logger.info(f" Final Balance:   ${final_balance:,.2f}")
        logger.info(f" Net P&L:         ${total_pnl_balance:,.2f} ({total_pnl_percent:.2f}%)")
        logger.info(f"   - Realized PnL:   ${total_realized_pnl:,.2f}")
        logger.info(f"   - Unrealized PnL: ${unrealized_pnl:,.2f}")
        logger.info(f" Total Buy Trades:    {num_buy_trades}")
        logger.info(f" Total Sell Trades:   {num_sell_trades} (Completed Trades)")
        logger.info(f" Success Rate:    {win_rate:.2f}%")
        logger.info(f" Payoff Ratio:    {payoff_ratio:.2f}")
        logger.info(f" Maximum Drawdown: {max_drawdown:.2%}")
        logger.info(f" Total Fees Paid: ${total_fees_usd:,.2f}")
        logger.info("========================================")

# Add a to_dict method to TradePoint if it doesn't exist, for easy conversion
def trade_point_to_dict(self):
    from dataclasses import asdict
    return asdict(self)
TradePoint.to_dict = trade_point_to_dict
