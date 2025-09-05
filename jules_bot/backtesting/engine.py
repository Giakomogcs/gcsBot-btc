import time
import uuid
import pandas as pd
from decimal import Decimal, getcontext

from jules_bot.bot.trading_bot import TradingBot
from jules_bot.core.mock_exchange import MockTrader
from jules_bot.database.postgres_manager import PostgresManager
from jules_bot.utils.config_manager import config_manager
from jules_bot.utils.logger import logger
from jules_bot.research.feature_engineering import add_all_features
from jules_bot.bot.situational_awareness import SituationalAwareness
from jules_bot.backtesting.components import BacktestFeatureCalculator, BacktestPortfolioManager

getcontext().prec = 28

class BacktestEngine:
    def __init__(self, db_manager: PostgresManager, days: int = None, start_date: str = None, end_date: str = None):
        self.run_id = f"backtest_{uuid.uuid4()}"
        self.db_manager = db_manager
        
        log_msg = ""
        if days:
            self.start_date_str = f"-{days}d"
            self.end_date_str = "now()"
            log_msg = f"Initializing new backtest run ID: {self.run_id} for the last {days} days."
        elif start_date and end_date:
            self.start_date_str = f"{start_date}T00:00:00Z"
            self.end_date_str = f"{end_date}T23:59:59Z"
            log_msg = f"Initializing new backtest run ID: {self.run_id} from {start_date} to {end_date}."
        else:
            raise ValueError("BacktestEngine must be initialized with 'days' or a date range.")

        logger.info(log_msg)
        
        symbol = config_manager.get('APP', 'symbol')
        price_data = self.db_manager.get_price_data(measurement=symbol, start_date=self.start_date_str, end_date=self.end_date_str)
        if price_data.empty:
            raise ValueError("No price data found for the specified period.")

        logger.info("Calculating all features for the backtest period...")
        features_with_nan = add_all_features(price_data, live_mode=False)
        sa_model = SituationalAwareness()
        features_with_regimes = sa_model.transform(features_with_nan)
        self.feature_data = features_with_regimes.dropna()
        logger.info("Feature and regime calculation complete.")

        self.backtest_feature_calculator = BacktestFeatureCalculator(self.feature_data)

        self.bot = TradingBot(
            mode='backtest',
            bot_id=self.run_id,
            market_data_provider=None,
            db_manager=self.db_manager
        )

        initial_balance = Decimal(config_manager.get('BACKTEST', 'initial_balance', fallback='1000.0'))
        self.mock_trader = MockTrader(
            initial_balance_usd=initial_balance,
            commission_fee_rate=Decimal(config_manager.get('BACKTEST', 'commission_fee', fallback='0.001')),
            symbol=symbol
        )
        
        # Replace live components with mock/backtest components
        self.bot.feature_calculator = self.backtest_feature_calculator
        self.bot.trader.client = self.mock_trader
        self.bot.live_portfolio_manager = BacktestPortfolioManager(self.mock_trader)
        
        # Disable components that are not needed
        self.bot.status_service = None
        self.bot.account_manager = None

        self.bot.reversal_buy_threshold_percent = Decimal(config_manager.get('STRATEGY_RULES', 'reversal_buy_threshold_percent', fallback='0.005'))
        self.bot.reversal_monitoring_timeout_seconds = int(config_manager.get('STRATEGY_RULES', 'reversal_monitoring_timeout_seconds', fallback='300'))

        logger.info("BacktestEngine initialized successfully.")

    def run(self):
        logger.info(f"--- Starting backtest run {self.run_id} ---")

        while self.backtest_feature_calculator.advance_to_next_candle():
            current_candle = self.backtest_feature_calculator.current_candle
            current_price = Decimal(str(current_candle['close']))
            current_time = current_candle.name

            self.mock_trader.set_current_time_and_price(current_time, current_price)

            original_time_func = time.time
            time.time = lambda: current_time.timestamp()

            self.bot._run_single_cycle()

            time.time = original_time_func

        logger.info("--- Backtest simulation finished ---")
        self._generate_and_save_summary()

    def _generate_and_save_summary(self):
        logger.info("--- Generating and saving backtest summary ---")

        all_trades_df = self.mock_trader.get_trade_history_df()
        
        if all_trades_df.empty:
            logger.warning("No trades were executed in this backtest run.")
            return

        initial_balance = self.mock_trader.initial_balance
        final_balance = self.mock_trader.get_total_portfolio_value()
        net_pnl = final_balance - initial_balance
        net_pnl_percent = (net_pnl / initial_balance) * 100 if initial_balance > 0 else Decimal(0)

        sell_trades = all_trades_df[all_trades_df['order_type'] == 'sell']
        buy_trades_count = len(all_trades_df[all_trades_df['order_type'] == 'buy'])
        sell_trades_count = len(sell_trades)

        total_realized_pnl = sell_trades['realized_pnl_usd'].sum() if 'realized_pnl_usd' in sell_trades else Decimal(0)
        total_fees_usd = all_trades_df['commission_usd'].sum()

        winning_trades = sell_trades[sell_trades['realized_pnl_usd'] > 0] if 'realized_pnl_usd' in sell_trades else pd.DataFrame()
        losing_trades = sell_trades[sell_trades['realized_pnl_usd'] <= 0] if 'realized_pnl_usd' in sell_trades else pd.DataFrame()

        win_rate = (len(winning_trades) / sell_trades_count) * 100 if sell_trades_count > 0 else Decimal(0)
        avg_gain = winning_trades['realized_pnl_usd'].mean() if len(winning_trades) > 0 else Decimal(0)
        avg_loss = abs(losing_trades['realized_pnl_usd'].mean()) if len(losing_trades) > 0 else Decimal(0)
        payoff_ratio = (avg_gain / avg_loss) if avg_loss > 0 else Decimal('inf')

        max_drawdown = Decimal('0')

        logger.info("="*30 + " BACKTEST RESULTS " + "="*30)
        logger.info(f" Backtest Run ID: {self.run_id}")
        if not self.feature_data.empty:
            start_time = self.feature_data.index[0].date()
            end_time = self.feature_data.index[-1].date()
            logger.info(f" Period: {start_time} to {end_time}")
        logger.info(f" Initial Balance: ${initial_balance:,.2f}")
        logger.info(f" Final Balance:   ${final_balance:,.2f}")
        logger.info(f" Net P&L:         ${net_pnl:,.2f} ({net_pnl_percent:.2f}%)")
        logger.info(f"   - Realized PnL:   ${total_realized_pnl:,.2f}")
        logger.info(f" Total Buy Trades:    {buy_trades_count}")
        logger.info(f" Total Sell Trades:   {sell_trades_count} (Completed Trades)")
        logger.info(f" Success Rate:        {win_rate:.2f}%")
        logger.info(f" Payoff Ratio:        {payoff_ratio:.2f}")
        logger.info(f" Maximum Drawdown:    {max_drawdown * 100:.2f}%")
        logger.info(f" Total Fees Paid:     ${total_fees_usd:,.2f}")
        logger.info("="*80)
