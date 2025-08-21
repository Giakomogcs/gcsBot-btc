import logging
import uuid
import pandas as pd
from decimal import Decimal, getcontext
from jules_bot.core.mock_exchange import MockTrader
from jules_bot.database.postgres_manager import PostgresManager
from jules_bot.utils.config_manager import config_manager
from jules_bot.core_logic.strategy_rules import StrategyRules
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

        backtest_settings = config_manager.get_section('BACKTEST')
        self.mock_trader = MockTrader(
            initial_balance_usd=Decimal(backtest_settings.get('initial_balance', '1000.0')),
            commission_fee_percent=Decimal(backtest_settings.get('commission_fee', '0.001')),
            symbol=symbol
        )
        self.strategy_rules = StrategyRules(config_manager)

    def run(self):
        logger.info(f"--- Starting backtest run {self.run_id} ---")

        strategy_rules = self.strategy_rules
        symbol = config_manager.get('APP', 'symbol')
        strategy_name = config_manager.get('APP', 'strategy_name', fallback='default_strategy')
        use_dynamic_capital = config_manager.getboolean('STRATEGY_RULES', 'use_dynamic_capital', fallback=False)
        wc_percentage = Decimal(config_manager.get('STRATEGY_RULES', 'working_capital_percentage', fallback='0.8'))
        max_open_positions = int(config_manager.get('STRATEGY_RULES', 'max_open_positions', fallback=20))
        min_trade_size = Decimal(config_manager.get('TRADING_STRATEGY', 'min_trade_size_usdt', fallback='10.0'))

        open_positions = {}
        portfolio_history = []

        for current_time, candle in self.feature_data.iterrows():
            current_price = Decimal(str(candle['close']))
            self.mock_trader.set_current_time_and_price(current_time, current_price)

            cash_balance = self.mock_trader.get_account_balance()
            current_open_positions_value = sum(pos['quantity'] * current_price for pos in open_positions.values())
            total_portfolio_value = cash_balance + current_open_positions_value
            portfolio_history.append(total_portfolio_value)

            for trade_id, position in list(open_positions.items()):
                trigger_price = position.get('trigger_price', Decimal('inf'))
                if current_price >= trigger_price:
                    sell_quantity = position['sell_quantity']
                    hodl_asset_amount = position['treasury_quantity']

                    success, sell_result = self.mock_trader.execute_sell({'quantity': sell_quantity})
                    if success:
                        buy_price = position['price']
                        sell_price = sell_result['price']
                        
                        realized_pnl_usd = strategy_rules.calculate_realized_pnl(
                            buy_price=buy_price,
                            sell_price=sell_price,
                            quantity_sold=sell_result['quantity']
                        )
                        commission_usd = sell_result['commission']
                        hodl_asset_value_at_sell = hodl_asset_amount * sell_result['price']

                        decision_context = candle.to_dict()
                        decision_context.pop('symbol', None)

                        trade_data = {
                            'run_id': self.run_id, 'strategy_name': strategy_name, 'symbol': symbol,
                            'trade_id': trade_id, 'exchange': "backtest_engine", 'order_type': "sell",
                            'status': "CLOSED", 'price': sell_result['price'], 'quantity': sell_result['quantity'],
                            'usd_value': sell_result['usd_value'], 'commission': commission_usd,
                            'commission_asset': "USDT", 'timestamp': current_time,
                            'decision_context': decision_context, 'commission_usd': commission_usd,
                            'realized_pnl_usd': realized_pnl_usd, 'hodl_asset_amount': hodl_asset_amount,
                            'hodl_asset_value_at_sell': hodl_asset_value_at_sell
                        }
                        self.trade_logger.update_trade(trade_data)

                        logger.info(f"SELL EXECUTED: TradeID: {trade_id} | Buy Price: ${position['price']:,.2f} | Sell Price: ${sell_result['price']:,.2f} | Realized PnL: ${realized_pnl_usd:,.2f} | HODL Amount: {hodl_asset_amount:.8f} BTC")

                        if hodl_asset_amount > Decimal('1e-8'):
                            treasury_trade_id = str(uuid.uuid4())
                            buy_price = position['price']
                            treasury_usd_value = hodl_asset_amount * buy_price
                            treasury_data = {
                                'run_id': self.run_id, 'environment': 'backtest', 'strategy_name': strategy_name,
                                'symbol': symbol, 'trade_id': treasury_trade_id, 'exchange': "backtest_engine",
                                'status': 'TREASURY', 'order_type': 'buy', 'price': buy_price,
                                'quantity': hodl_asset_amount, 'usd_value': treasury_usd_value,
                                'timestamp': current_time,
                                'decision_context': {'source': 'treasury', 'original_trade_id': trade_id}
                            }
                            self.trade_logger.log_trade(treasury_data)
                            logger.info(f"TREASURY CREATED: TradeID: {treasury_trade_id} | Quantity: {hodl_asset_amount:.8f} BTC | Value at cost: ${treasury_usd_value:,.2f}")

                        del open_positions[trade_id]

            buy_check_passed = False
            if use_dynamic_capital:
                working_capital = total_portfolio_value * wc_percentage
                capital_in_use = sum(pos['usd_value'] for pos in open_positions.values())
                available_buying_power = working_capital - capital_in_use
                buy_amount_usdt = strategy_rules.get_next_buy_amount(cash_balance)
                if buy_amount_usdt <= available_buying_power:
                    buy_check_passed = True
            else:
                if len(open_positions) < max_open_positions:
                    buy_check_passed = True

            if buy_check_passed:
                market_data = candle.to_dict()
                should_buy, regime, reason = strategy_rules.evaluate_buy_signal(market_data, len(open_positions))
                if should_buy:
                    buy_amount_usdt = strategy_rules.get_next_buy_amount(cash_balance)
                    if cash_balance >= min_trade_size and buy_amount_usdt >= min_trade_size:
                        success, buy_result = self.mock_trader.execute_buy(buy_amount_usdt)
                        if success:
                            new_trade_id = str(uuid.uuid4())
                            buy_price = buy_result['price']
                            total_cost_invested = buy_result['usd_value']
                            total_quantity_bought = buy_result['quantity']

                            take_profit_details = strategy_rules.calculate_take_profit_details(
                                total_cost_invested=total_cost_invested,
                                total_quantity_bought=total_quantity_bought
                            )

                            open_positions[new_trade_id] = {
                                'price': buy_price,
                                'quantity': total_quantity_bought,
                                'usd_value': total_cost_invested,
                                'trigger_price': take_profit_details['trigger_price'],
                                'sell_quantity': take_profit_details['sell_quantity'],
                                'treasury_quantity': take_profit_details['treasury_quantity']
                            }

                            # Log the new "OPEN" position to the database
                            decision_context = candle.to_dict()
                            decision_context.pop('symbol', None)

                            trade_data = {
                                'run_id': self.run_id, 'strategy_name': strategy_name, 'symbol': symbol,
                                'trade_id': new_trade_id, 'exchange': "backtest_engine", 'order_type': "buy",
                                'status': "OPEN", 'price': buy_price, 'quantity': total_quantity_bought,
                                'usd_value': total_cost_invested, 'commission': buy_result['commission'],
                                'commission_asset': "USDT", 'timestamp': current_time,
                                'decision_context': decision_context,
                                'trigger_price': float(take_profit_details['trigger_price']),
                                'sell_quantity': float(take_profit_details['sell_quantity']),
                                'treasury_quantity': float(take_profit_details['treasury_quantity']),
                                'commission_usd': buy_result['commission']
                            }
                            self.trade_logger.log_trade(trade_data)
                            logger.info(f"BUY EXECUTED: TradeID: {new_trade_id} | Price: ${buy_price:,.2f} | Qty: {total_quantity_bought:.8f}")

        self._generate_and_save_summary(open_positions, portfolio_history)
        logger.info(f"--- Backtest {self.run_id} finished ---")

    def _generate_and_save_summary(self, open_positions: dict, portfolio_history: list[Decimal]):
        logger.info("--- Generating and saving backtest summary ---")

        all_trades_for_run = self.db_manager.get_trades_by_run_id(self.run_id)

        # Convert to DataFrame for easier analysis
        if not all_trades_for_run:
            logger.warning("No trades were executed in this backtest run.")
            all_trades_df = pd.DataFrame()
        else:
            all_trades_df = pd.DataFrame([t.to_dict() for t in all_trades_for_run])
            # Convert numeric columns to Decimal for precision
            for col in ['price', 'quantity', 'usd_value', 'commission', 'commission_usd', 'realized_pnl_usd', 'hodl_asset_amount', 'hodl_asset_value_at_sell']:
                if col in all_trades_df.columns:
                    all_trades_df[col] = all_trades_df[col].apply(lambda x: Decimal(str(x)) if x is not None else Decimal(0))

        # --- METRIC CALCULATIONS ---
        initial_balance = self.mock_trader.initial_balance
        final_balance = self.mock_trader.get_total_portfolio_value()
        net_pnl = final_balance - initial_balance
        net_pnl_percent = (net_pnl / initial_balance) * 100 if initial_balance > 0 else Decimal(0)

        buy_trades = all_trades_df[all_trades_df['order_type'] == 'buy']
        sell_trades = all_trades_df[all_trades_df['status'] == 'CLOSED']

        total_realized_pnl = sell_trades['realized_pnl_usd'].sum()
        total_fees_usd = all_trades_df['commission_usd'].sum()

        winning_trades = sell_trades[sell_trades['realized_pnl_usd'] > 0]
        losing_trades = sell_trades[sell_trades['realized_pnl_usd'] <= 0]

        win_rate = (len(winning_trades) / len(sell_trades)) * 100 if len(sell_trades) > 0 else Decimal(0)

        avg_gain = winning_trades['realized_pnl_usd'].mean() if len(winning_trades) > 0 else Decimal(0)
        avg_loss = abs(losing_trades['realized_pnl_usd'].mean()) if len(losing_trades) > 0 else Decimal(0)
        payoff_ratio = avg_gain / avg_loss if avg_loss > 0 else Decimal('inf')

        unrealized_pnl = sum((pos['quantity'] * self.mock_trader.get_current_price()) - pos['usd_value'] for pos in open_positions.values())

        # Max Drawdown Calculation
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

        # Treasury Calculation
        treasury_df = all_trades_df[all_trades_df['status'] == 'TREASURY']
        btc_treasury_amount = treasury_df['quantity'].sum()
        btc_treasury_value = btc_treasury_amount * self.mock_trader.get_current_price()

        # --- LOGGING ---
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
        logger.info(f"   - Unrealized PnL: ${unrealized_pnl:,.2f}")
        logger.info(f" Total Buy Trades:    {len(buy_trades)}")
        logger.info(f" Total Sell Trades:   {len(sell_trades)} (Completed Trades)")
        logger.info(f" Success Rate:        {win_rate:.2f}%")
        logger.info(f" Payoff Ratio:        {payoff_ratio:.2f}")
        logger.info(f" Maximum Drawdown:    {max_drawdown:.2%}")
        logger.info(f" Total Fees Paid:     ${total_fees_usd:,.2f}")
        logger.info(f" BTC Treasury:        {btc_treasury_amount:.8f} BTC (${btc_treasury_value:,.2f})")
        logger.info("="*80)

# Add a to_dict method to TradePoint if it doesn't exist, for easy conversion
def trade_point_to_dict(self):
    from dataclasses import asdict
    return asdict(self)
TradePoint.to_dict = trade_point_to_dict
