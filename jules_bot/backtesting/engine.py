import logging
import uuid
import pandas as pd
import os
from decimal import Decimal, getcontext
from jules_bot.core.mock_exchange import MockTrader
from jules_bot.database.postgres_manager import PostgresManager
from jules_bot.utils.config_manager import config_manager
from jules_bot.core_logic.strategy_rules import StrategyRules
from jules_bot.core_logic.capital_manager import CapitalManager
from jules_bot.core_logic.dynamic_parameters import DynamicParameters
from jules_bot.bot.situational_awareness import SituationalAwareness
from jules_bot.utils.logger import logger
from jules_bot.core.schemas import TradePoint
from jules_bot.research.feature_engineering import add_all_features
from jules_bot.services.trade_logger import TradeLogger
from jules_bot.core_logic.state_manager import StateManager
from jules_bot.bot.unified_logic import UnifiedTradingLogic

getcontext().prec = 28

class MockPortfolioManager:
    """A mock portfolio manager for backtesting that mimics LivePortfolioManager."""
    def __init__(self, mock_trader, state_manager):
        self.mock_trader = mock_trader
        self.state_manager = state_manager
        self.quote_asset = "USDT"

    def get_total_portfolio_value(self, current_price: Decimal, force_recalculation: bool = False) -> Decimal:
        cash_balance = self.mock_trader.get_account_balance(asset=self.quote_asset)
        open_positions = self.state_manager.get_open_positions()
        open_positions_value = sum(
            Decimal(p.quantity) * current_price for p in open_positions
        )
        return cash_balance + open_positions_value

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
            self.start_date_str = f"{start_date}T00:00:00Z"
            self.end_date_str = f"{end_date}T23:59:59Z"
            log_msg = f"Initializing new backtest run with ID: {self.run_id} from {start_date} to {end_date}."
        else:
            raise ValueError("Backtester must be initialized with either 'days' or both 'start_date' and 'end_date'.")

        logger.info(log_msg)
        self.trade_logger = TradeLogger(mode='backtest', db_manager=self.db_manager)
        symbol = config_manager.get('APP', 'symbol')
        
        price_data = self.db_manager.get_price_data(measurement=symbol, start_date=self.start_date_str, end_date=self.end_date_str)
        if price_data.empty:
            raise ValueError("No price data found for the specified period. Cannot run backtest.")

        logger.info("Calculating features for the entire backtest period...")
        self.feature_data = add_all_features(price_data, live_mode=False).dropna()
        logger.info("Feature calculation complete.")

        initial_balance_str = config_manager.get('BACKTEST', 'initial_balance') or '1000.0'
        commission_fee_str = config_manager.get('BACKTEST', 'commission_fee') or '0.001'
        self.mock_trader = MockTrader(
            initial_balance_usd=Decimal(initial_balance_str),
            commission_fee_rate=Decimal(commission_fee_str),
            symbol=symbol
        )
        self.strategy_rules = StrategyRules(config_manager)
        self.capital_manager = CapitalManager(config_manager, self.strategy_rules, db_manager=self.db_manager)
        self.dynamic_params = DynamicParameters(config_manager)
        self.sa_model = SituationalAwareness()
        self.feature_data = self.sa_model.transform(self.feature_data)
        
        # Use the real StateManager
        self.state_manager = StateManager(mode='backtest', bot_id=self.run_id, db_manager=self.db_manager, feature_calculator=None) # No live feature calculator
        
        # Use the mock portfolio manager
        self.mock_portfolio_manager = MockPortfolioManager(self.mock_trader, self.state_manager)

        # Instantiate the unified logic engine
        self.unified_logic = UnifiedTradingLogic(
            bot_id=self.run_id,
            mode='backtest',
            trader=self.mock_trader,
            state_manager=self.state_manager,
            capital_manager=self.capital_manager,
            strategy_rules=self.strategy_rules,
            dynamic_params=self.dynamic_params,
            sa_instance=self.sa_model,
            portfolio_manager=self.mock_portfolio_manager,
            db_manager=self.db_manager
        )

    def run(self):
        logger.info(f"--- Starting backtest run {self.run_id} ---")

        strategy_rules = self.strategy_rules
        symbol = config_manager.get('APP', 'symbol')
        strategy_name = config_manager.get('APP', 'strategy_name', fallback='default_strategy')
        min_trade_size = Decimal(config_manager.get('TRADING_STRATEGY', 'min_trade_size_usdt', fallback='10.0'))

        portfolio_history = []

        # The Backtester now iterates through the data and calls the unified logic,
        # just like the live bot does.
        for current_time, candle in self.feature_data.iterrows():
            self.mock_trader.set_current_time_and_price(current_time, candle['close'])
            
            # The unified logic requires the features for the current candle,
            # but also the historical data for some indicators. We pass a slice
            # of the dataframe up to the current point in time.
            current_data_slice = self.feature_data.loc[:current_time]
            
            # Run the unified trading cycle
            cycle_results = self.unified_logic.run_trading_cycle(current_data_slice)

            # Record portfolio value for this timestep
            if cycle_results:
                _, _, _, _, portfolio_val = cycle_results
                portfolio_history.append(portfolio_val)

        # After the loop, all trades are already logged by the StateManager.
        # We just need to generate the final summary.
        self._generate_and_save_summary(self.state_manager.get_open_positions(), portfolio_history)
        logger.info(f"--- Backtest {self.run_id} finished ---")

    def _log_trades_to_db(self, trades: list):
        # This method is no longer needed, as the StateManager and UnifiedLogic
        # handle logging trades directly to the database.
        pass

    def _generate_and_save_summary(self, open_positions: dict, portfolio_history: list[Decimal]):
        logger.info("--- Generating and saving backtest summary ---")

        all_trades_for_run = self.db_manager.get_trades_by_run_id(self.run_id)
        
        if not all_trades_for_run:
            logger.warning("No trades were executed in this backtest run.")
            all_trades_df = pd.DataFrame()
        else:
            all_trades_df = pd.DataFrame([t.to_dict() for t in all_trades_for_run])
            for col in ['price', 'quantity', 'usd_value', 'commission', 'commission_usd', 'realized_pnl_usd', 'hodl_asset_amount', 'hodl_asset_value_at_sell']:
                if col in all_trades_df.columns:
                    all_trades_df[col] = all_trades_df[col].apply(lambda x: Decimal(str(x)) if pd.notna(x) else Decimal(0))

        initial_balance = self.mock_trader.initial_balance
        final_balance = self.mock_trader.get_total_portfolio_value()
        net_pnl = final_balance - initial_balance
        net_pnl_percent = (net_pnl / initial_balance) * 100 if initial_balance > 0 else Decimal(0)

        unrealized_pnl = sum(
            self.strategy_rules.calculate_net_unrealized_pnl(
                entry_price=pos['price'], current_price=self.mock_trader.get_current_price(),
                total_quantity=pos['quantity'], buy_commission_usd=pos.get('commission_usd', Decimal('0'))
            ) for pos in open_positions.values()
        )

        total_realized_pnl = Decimal(0)
        total_fees_usd = Decimal(0)
        win_rate = Decimal(0)
        payoff_ratio = Decimal(0)
        avg_gain = Decimal(0)
        avg_loss = Decimal(0)
        buy_trades_count = 0
        sell_trades_count = 0

        if not all_trades_df.empty:
            sell_trades = all_trades_df[all_trades_df['status'] == 'CLOSED']
            buy_trades_count = len(all_trades_df[all_trades_df['order_type'] == 'buy'])
            sell_trades_count = len(sell_trades)

            total_realized_pnl = sell_trades['realized_pnl_usd'].sum()
            total_fees_usd = all_trades_df['commission_usd'].sum()

            winning_trades = sell_trades[sell_trades['realized_pnl_usd'] > 0]
            losing_trades = sell_trades[sell_trades['realized_pnl_usd'] <= 0]

            if sell_trades_count > 0:
                win_rate = (len(winning_trades) / sell_trades_count) * 100
            
            if len(winning_trades) > 0:
                avg_gain = Decimal(str(winning_trades['realized_pnl_usd'].mean()))
            
            if len(losing_trades) > 0:
                avg_loss = Decimal(str(abs(losing_trades['realized_pnl_usd'].mean())))
            
            if avg_loss > 0:
                payoff_ratio = avg_gain / avg_loss

        max_drawdown = Decimal(0)
        peak = -Decimal('inf')
        if portfolio_history:
            peak = portfolio_history[0]
            for value in portfolio_history:
                if value > peak:
                    peak = value
                drawdown = (peak - value) / peak if peak > 0 else Decimal(0)
                if drawdown > max_drawdown:
                    max_drawdown = drawdown

        logger.info("="*30 + " BACKTEST RESULTS " + "="*30)
        logger.info(f" Backtest Run ID: {self.run_id}")
        if not self.feature_data.empty:
            start_time = self.feature_data.index[0].date()
            end_time = self.feature_data.index[-1].date()
            logger.info(f" Period: {start_time} to {end_time}")
        logger.info(f" Initial Balance: ${initial_balance:,.2f}")
        logger.info(f" Final Balance:   ${final_balance:,.2f}")
        logger.info(f" Net P&L:         ${net_pnl:,.2f} ({net_pnl_percent:.2f}%%)")
        logger.info(f"   - Realized PnL:   ${total_realized_pnl:,.2f}")
        logger.info(f"   - Unrealized PnL: ${unrealized_pnl:,.2f}")
        logger.info(f" Total Buy Trades:    {buy_trades_count}")
        logger.info(f" Total Sell Trades:   {sell_trades_count} (Completed Trades)")
        logger.info(f" Success Rate:        {win_rate:.2f}%%")
        logger.info(f" Payoff Ratio:        {payoff_ratio:.2f}")
        logger.info(f" Maximum Drawdown:    {max_drawdown * 100:.2f}%%")
        logger.info(f" Total Fees Paid:     ${total_fees_usd:,.2f}")
        logger.info("="*80)

def trade_point_to_dict(self):
    from dataclasses import asdict
    return asdict(self)
TradePoint.to_dict = trade_point_to_dict
