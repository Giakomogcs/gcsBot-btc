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

getcontext().prec = 28

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
        self.capital_manager = CapitalManager(config_manager, self.strategy_rules)

        # --- Dynamic Strategy Components ---
        self.dynamic_params = DynamicParameters(config_manager)
        
        logger.info("Initializing the Situational Awareness model...")
        self.sa_model = SituationalAwareness()
        
        self.feature_data = self.sa_model.transform(self.feature_data)
        logger.info("Market regimes calculated for the entire backtest period.")

    def run(self):
        logger.info(f"--- Starting backtest run {self.run_id} ---")

        strategy_rules = self.strategy_rules
        symbol = config_manager.get('APP', 'symbol')
        strategy_name = config_manager.get('APP', 'strategy_name', fallback='default_strategy')
        min_trade_size = Decimal(config_manager.get('TRADING_STRATEGY', 'min_trade_size_usdt', fallback='10.0'))

        open_positions = {}
        portfolio_history = []
        all_trades_for_run = []

        for current_time, candle in self.feature_data.iterrows():
            current_price = Decimal(str(candle['close']))
            self.mock_trader.set_current_time_and_price(current_time, current_price)

            current_regime = candle.get('market_regime', -1)
            self.dynamic_params.update_parameters(int(current_regime))
            current_params = self.dynamic_params.parameters

            cash_balance = self.mock_trader.get_account_balance()
            current_open_positions_value = sum(pos['quantity'] * current_price for pos in open_positions.values())
            total_portfolio_value = cash_balance + current_open_positions_value
            portfolio_history.append(total_portfolio_value)

            positions_to_sell_now = []
            for trade_id, position in list(open_positions.items()):
                sell_target_price = position.get('sell_target_price', Decimal('inf'))
                if current_price >= sell_target_price:
                    positions_to_sell_now.append(position)
                    continue

                entry_price = position['price']
                break_even_price = self.strategy_rules.calculate_break_even_price(entry_price)
                current_pnl_percent = (current_price / entry_price) - Decimal('1') if entry_price > 0 else Decimal('0')

                if not position.get('is_smart_trailing_active') and current_pnl_percent >= self.strategy_rules.smart_trailing_activation_profit_percent:
                    position['is_smart_trailing_active'] = True
                    position['smart_trailing_highest_price'] = current_price
                    continue

                if position.get('is_smart_trailing_active'):
                    highest_price = position.get('smart_trailing_highest_price', current_price)
                    if current_price < break_even_price:
                        position['is_smart_trailing_active'] = False
                        continue
                    if current_price > highest_price:
                        position['smart_trailing_highest_price'] = current_price
                        highest_price = current_price
                    stop_price = highest_price * (Decimal('1') - self.strategy_rules.trailing_stop_percent)
                    if current_price <= stop_price:
                        positions_to_sell_now.append(position)

            if positions_to_sell_now:
                for position in positions_to_sell_now:
                    trade_id = position['trade_id']
                    original_quantity = position['quantity']
                    sell_quantity = original_quantity * strategy_rules.sell_factor

                    success, sell_result = self.mock_trader.execute_sell({'quantity': sell_quantity}, self.run_id, candle.to_dict())
                    if success:
                        realized_pnl_usd = strategy_rules.calculate_realized_pnl(
                            buy_price=position['price'], sell_price=sell_result['price'], quantity_sold=sell_result['quantity'],
                            buy_commission_usd=position['commission_usd'], sell_commission_usd=sell_result.get('commission_usd', Decimal('0')),
                            buy_quantity=position['quantity']
                        )
                        hodl_asset_amount = original_quantity - sell_quantity

                        trade_data = {
                            'run_id': self.run_id, 'strategy_name': strategy_name, 'symbol': symbol,
                            'trade_id': trade_id, 'exchange': "backtest_engine", 'order_type': "sell",
                            'status': "CLOSED", 'price': sell_result['price'], 'quantity': sell_result['quantity'],
                            'usd_value': sell_result['usd_value'], 'commission': sell_result.get('commission_usd', Decimal('0')),
                            'commission_asset': "USDT", 'timestamp': current_time, 'decision_context': candle.to_dict(),
                            'commission_usd': sell_result.get('commission_usd', Decimal('0')), 'realized_pnl_usd': realized_pnl_usd
                        }
                        all_trades_for_run.append(trade_data)
                        del open_positions[trade_id]

            # BUY LOGIC
            market_data = candle.to_dict()
            recent_trades_for_difficulty = [t for t in all_trades_for_run if t['timestamp'] <= current_time]

            buy_amount_usdt, op_mode, reason, _, diff_factor = self.capital_manager.get_buy_order_details(
                market_data=market_data, open_positions=list(open_positions.values()),
                portfolio_value=total_portfolio_value, free_cash=cash_balance,
                params=current_params, trade_history=recent_trades_for_difficulty
            )

            if buy_amount_usdt > 0 and cash_balance >= min_trade_size:
                decision_context_buy = {**candle.to_dict(), 'operating_mode': op_mode, 'buy_trigger_reason': reason, 'market_regime': current_regime}
                success, buy_result = self.mock_trader.execute_buy(buy_amount_usdt, self.run_id, decision_context_buy)
                if success:
                    new_trade_id = str(uuid.uuid4())
                    sell_target_price = strategy_rules.calculate_sell_target_price(buy_result['price'], buy_result['quantity'], params=current_params)

                    position_data = {
                        'trade_id': new_trade_id, 'price': buy_result['price'], 'quantity': buy_result['quantity'],
                        'usd_value': buy_result['usd_value'], 'sell_target_price': sell_target_price,
                        'commission_usd': buy_result.get('commission_usd', Decimal('0')),
                        'is_smart_trailing_active': False, 'smart_trailing_highest_price': None
                    }
                    open_positions[new_trade_id] = position_data

                    trade_data = {
                        'run_id': self.run_id, 'strategy_name': strategy_name, 'symbol': symbol,
                        'trade_id': new_trade_id, 'exchange': "backtest_engine", 'order_type': "buy",
                        'status': "OPEN", 'price': buy_result['price'], 'quantity': buy_result['quantity'],
                        'usd_value': buy_result['usd_value'], 'commission': buy_result.get('commission_usd', Decimal('0')),
                        'commission_asset': "USDT", 'timestamp': current_time,
                        'decision_context': decision_context_buy, 'sell_target_price': sell_target_price,
                        'commission_usd': buy_result.get('commission_usd', Decimal('0'))
                    }
                    all_trades_for_run.append(trade_data)

        self._log_trades_to_db(all_trades_for_run)
        self._generate_and_save_summary(open_positions, portfolio_history)
        logger.info(f"--- Backtest {self.run_id} finished ---")

    def _log_trades_to_db(self, trades: list):
        if not trades:
            return
        logger.info(f"Logging {len(trades)} trades from backtest run to database...")
        for trade_data in trades:
            if trade_data['status'] == 'OPEN':
                self.trade_logger.log_trade(trade_data)
            else: # status is 'CLOSED'
                # For closed trades, we need to log the initial buy and then update it
                # This is a simplification; a more robust solution would be needed for complex scenarios
                # but for this backtester, it's sufficient.
                buy_trade_data = {**trade_data}
                buy_trade_data['status'] = 'OPEN'
                self.trade_logger.log_trade(buy_trade_data)
                self.trade_logger.update_trade(trade_data)

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
