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
        
        # A SA agora calcula os regimes para todo o conjunto de dados de uma vez, usando uma janela rolante
        # para evitar o lookahead bias. A coluna 'market_regime' é adicionada ao feature_data.
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

        # Itera sobre os dados que agora já contêm os regimes de mercado pré-calculados
        for current_time, candle in self.feature_data.iterrows():
            current_price = Decimal(str(candle['close']))
            self.mock_trader.set_current_time_and_price(current_time, current_price)

            # --- DYNAMIC STRATEGY LOGIC ---
            # O regime de mercado é obtido diretamente da vela (candle), pois foi pré-calculado
            current_regime = candle.get('market_regime', -1)
            
            # Ensure the regime is an integer for correct config section lookup
            self.dynamic_params.update_parameters(int(current_regime))
            current_params = self.dynamic_params.parameters
            # --- END DYNAMIC STRATEGY LOGIC ---

            cash_balance = self.mock_trader.get_account_balance()
            current_open_positions_value = sum(pos['quantity'] * current_price for pos in open_positions.values())
            total_portfolio_value = cash_balance + current_open_positions_value
            portfolio_history.append(total_portfolio_value)

            for trade_id, position in list(open_positions.items()):
                target_price = position.get('sell_target_price', Decimal('inf'))
                if current_price >= target_price:
                    original_quantity = position['quantity']
                    sell_quantity = original_quantity * strategy_rules.sell_factor

                    decision_context_sell = candle.to_dict()
                    success, sell_result = self.mock_trader.execute_sell(
                        {'quantity': sell_quantity}, self.run_id, decision_context_sell
                    )
                    if success:
                        buy_price = position['price']
                        sell_price = sell_result['price']
                        
                        sell_commission_usd = sell_result.get('commission_usd', Decimal('0'))
                        realized_pnl_usd = strategy_rules.calculate_realized_pnl(
                            buy_price=buy_price,
                            sell_price=sell_price,
                            quantity_sold=sell_result['quantity'],
                            buy_commission_usd=position['commission_usd'],
                            sell_commission_usd=sell_commission_usd,
                            buy_quantity=position['quantity']
                        )
                        commission_usd = sell_result.get('commission_usd', Decimal('0'))
                        hodl_asset_amount = original_quantity - sell_quantity
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

            market_data = candle.to_dict()
            buy_amount_usdt, operating_mode, reason, _ = self.capital_manager.get_buy_order_details(
                market_data=market_data,
                open_positions=list(open_positions.values()),
                portfolio_value=total_portfolio_value,
                free_cash=cash_balance,
                params=current_params
            )

            if buy_amount_usdt > 0 and cash_balance >= min_trade_size:
                decision_context_buy = candle.to_dict()
                decision_context_buy['operating_mode'] = operating_mode
                decision_context_buy['buy_trigger_reason'] = reason
                decision_context_buy['market_regime'] = current_regime
                success, buy_result = self.mock_trader.execute_buy(
                    buy_amount_usdt, self.run_id, decision_context_buy
                )
                if success:
                    new_trade_id = str(uuid.uuid4())
                    buy_price = buy_result['price']
                    quantity_bought = buy_result['quantity']
                    sell_target_price = strategy_rules.calculate_sell_target_price(buy_price, quantity_bought, params=current_params)

                    open_positions[new_trade_id] = {
                        'price': buy_price, 'quantity': buy_result['quantity'],
                        'usd_value': buy_result['usd_value'], 'sell_target_price': sell_target_price,
                        'commission_usd': buy_result.get('commission_usd', Decimal('0'))
                    }

                    decision_context = candle.to_dict()
                    decision_context.pop('symbol', None)
                    decision_context['operating_mode'] = operating_mode
                    decision_context['buy_trigger_reason'] = reason
                    decision_context['market_regime'] = current_regime

                    trade_data = {
                        'run_id': self.run_id, 'strategy_name': strategy_name, 'symbol': symbol,
                        'trade_id': new_trade_id, 'exchange': "backtest_engine", 'order_type': "buy",
                        'status': "OPEN", 'price': buy_price, 'quantity': buy_result['quantity'],
                        'usd_value': buy_result['usd_value'], 'commission': buy_result.get('commission_usd', Decimal('0')),
                        'commission_asset': "USDT", 'timestamp': current_time,
                        'decision_context': decision_context, 'sell_target_price': sell_target_price,
                        'commission_usd': buy_result.get('commission_usd', Decimal('0'))
                    }
                    self.trade_logger.log_trade(trade_data)
                    logger.info(f"BUY EXECUTED: TradeID: {new_trade_id} | Price: ${buy_price:,.2f} | Qty: {buy_result['quantity']:.8f} | Regime: {current_regime}")

        self._generate_and_save_summary(open_positions, portfolio_history)
        logger.info(f"--- Backtest {self.run_id} finished ---")

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
                    # Use pd.isna to correctly handle both None and np.nan from pandas.
                    all_trades_df[col] = all_trades_df[col].apply(lambda x: Decimal(str(x)) if not pd.isna(x) else Decimal(0))

        initial_balance = self.mock_trader.initial_balance
        final_balance = self.mock_trader.get_total_portfolio_value()
        net_pnl = final_balance - initial_balance
        net_pnl_percent = (net_pnl / initial_balance) * 100 if initial_balance > 0 else Decimal(0)

        # Correctly calculate unrealized PnL by reusing the fee-aware pnl calculation method.
        # This simulates closing all open positions at the current market price.
        unrealized_pnl = sum(
            self.strategy_rules.calculate_net_unrealized_pnl(
                entry_price=pos['price'],
                current_price=self.mock_trader.get_current_price(),
                total_quantity=pos['quantity'],
                buy_commission_usd=pos.get('commission', Decimal('0'))
            ) for pos in open_positions.values()
        )

        # Initialize metrics to default values
        total_realized_pnl = Decimal(0)
        total_fees_usd = Decimal(0)
        win_rate = Decimal(0)
        payoff_ratio = Decimal(0)
        avg_gain = Decimal(0)
        avg_loss = Decimal(0)
        buy_trades_count = 0
        sell_trades_count = 0
        btc_treasury_amount = Decimal(0)
        btc_treasury_value = Decimal(0)

        if not all_trades_df.empty:
            buy_trades = all_trades_df[all_trades_df['status'] != 'TREASURY']
            sell_trades = all_trades_df[all_trades_df['status'] == 'CLOSED']
            buy_trades_count = len(buy_trades)
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

            treasury_df = all_trades_df[all_trades_df['status'] == 'TREASURY']
            if not treasury_df.empty:
                btc_treasury_amount = treasury_df['quantity'].sum()
                btc_treasury_value = btc_treasury_amount * self.mock_trader.get_current_price()

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
        logger.info(f" BTC Treasury:        {btc_treasury_amount:.8f} BTC (${btc_treasury_value:,.2f})")
        logger.info("="*80)

def trade_point_to_dict(self):
    from dataclasses import asdict
    return asdict(self)
TradePoint.to_dict = trade_point_to_dict
