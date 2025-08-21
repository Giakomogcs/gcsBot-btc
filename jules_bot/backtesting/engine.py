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
from jules_bot.core_logic.state_manager import StateManager
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
        self.state_manager = StateManager(mode='backtest', bot_id=self.run_id, db_manager=self.db_manager)
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
        use_dynamic_capital = config_manager.getboolean('STRATEGY_RULES', 'use_dynamic_capital', fallback=False)
        wc_percentage = Decimal(config_manager.get('STRATEGY_RULES', 'working_capital_percentage', fallback='0.8'))
        max_open_positions = int(config_manager.get('STRATEGY_RULES', 'max_open_positions', fallback=20))
        min_trade_size = Decimal(config_manager.get('TRADING_STRATEGY', 'min_trade_size_usdt', fallback='10.0'))

        portfolio_history = []

        for current_time, candle in self.feature_data.iterrows():
            current_price = Decimal(str(candle['close']))
            self.mock_trader.set_current_time_and_price(current_time, current_price)

            open_positions = self.state_manager.get_open_positions()
            cash_balance = self.mock_trader.get_account_balance()

            # Calculate current portfolio value
            open_positions_value = sum(Decimal(p.quantity) * current_price for p in open_positions)
            total_portfolio_value = cash_balance + open_positions_value
            portfolio_history.append(total_portfolio_value)

            # --- SELL LOGIC ---
            positions_to_sell = [p for p in open_positions if current_price >= Decimal(str(p.sell_target_price or 'inf'))]
            if positions_to_sell:
                for position in positions_to_sell:
                    original_quantity = Decimal(str(position.quantity))
                    sell_quantity = original_quantity * strategy_rules.sell_factor
                    hodl_asset_amount = original_quantity - sell_quantity

                    # MockTrader needs a dict-like object for position data
                    sell_position_data = {'quantity': sell_quantity}
                    success, sell_result = self.mock_trader.execute_sell(sell_position_data)

                    if success:
                        buy_price = Decimal(str(position.price))
                        sell_price = Decimal(str(sell_result.get('price')))
                        
                        realized_pnl_usd = strategy_rules.calculate_realized_pnl(buy_price, sell_price, sell_quantity)
                        hodl_asset_value_at_sell = hodl_asset_amount * sell_price
                        commission_usd = Decimal(str(sell_result.get('commission', '0')))

                        # Add extra data to sell_result for state manager
                        sell_result.update({
                            "commission_usd": commission_usd,
                            "realized_pnl_usd": realized_pnl_usd,
                            "hodl_asset_amount": hodl_asset_amount,
                            "hodl_asset_value_at_sell": hodl_asset_value_at_sell,
                            "decision_context": candle.to_dict()
                        })

                        self.state_manager.record_partial_sell(
                            original_trade_id=position.trade_id,
                            remaining_quantity=hodl_asset_amount,
                            sell_data=sell_result
                        )
                        logger.info(f"SELL EXECUTED: TradeID: {position.trade_id} | Buy Price: ${buy_price:,.2f} | Sell Price: ${sell_price:,.2f} | Realized PnL: ${realized_pnl_usd:,.2f} | HODL Amount: {hodl_asset_amount:.8f} BTC")

            # --- BUY LOGIC ---
            # Re-fetch open positions after potential sells
            open_positions = self.state_manager.get_open_positions()

            buy_check_passed = False
            if use_dynamic_capital:
                working_capital = total_portfolio_value * wc_percentage
                capital_in_use = sum(Decimal(p.quantity) * Decimal(p.price) for p in open_positions)
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

                        decision_context = { "market_regime": regime, "buy_trigger_reason": reason }
                        success, buy_result = self.mock_trader.execute_buy(buy_amount_usdt, decision_context)

                        if success:
                            purchase_price = Decimal(buy_result.get('price'))
                            sell_target_price = strategy_rules.calculate_sell_target_price(purchase_price)

                            self.state_manager.create_new_position(buy_result, sell_target_price)
                            logger.info(f"BUY EXECUTED: TradeID: {buy_result['trade_id']} | Price: ${purchase_price:,.2f} | Qty: {buy_result['quantity']:.8f}")

        self._generate_and_save_summary(portfolio_history)
        logger.info(f"--- Backtest {self.run_id} finished ---")

    def _generate_and_save_summary(self, portfolio_history: list[Decimal]):
        logger.info("--- Generating and saving backtest summary ---")

        all_trades_for_run = self.db_manager.get_trades_by_run_id(self.run_id)

        if not all_trades_for_run:
            logger.warning("No trades were executed in this backtest run.")
            all_trades_df = pd.DataFrame()
        else:
            all_trades_df = pd.DataFrame([t.to_dict() for t in all_trades_for_run])
            for col in ['price', 'quantity', 'usd_value', 'commission', 'commission_usd', 'realized_pnl_usd', 'hodl_asset_amount', 'hodl_asset_value_at_sell']:
                if col in all_trades_df.columns:
                    all_trades_df[col] = all_trades_df[col].apply(lambda x: Decimal(str(x)) if x is not None else Decimal(0))

        initial_balance = self.mock_trader.initial_balance
        final_balance = self.mock_trader.get_total_portfolio_value()
        net_pnl = final_balance - initial_balance
        net_pnl_percent = (net_pnl / initial_balance) * 100 if initial_balance > 0 else Decimal(0)

        buy_trades = all_trades_df[(all_trades_df['order_type'] == 'buy') & (all_trades_df['status'] != 'TREASURY')]
        sell_trades = all_trades_df[all_trades_df['status'] == 'CLOSED']
        treasury_trades = all_trades_df[all_trades_df['status'] == 'TREASURY']

        total_realized_pnl = sell_trades['realized_pnl_usd'].sum()
        total_fees_usd = all_trades_df['commission_usd'].sum()

        winning_trades = sell_trades[sell_trades['realized_pnl_usd'] > 0]
        losing_trades = sell_trades[sell_trades['realized_pnl_usd'] <= 0]

        win_rate = (len(winning_trades) / len(sell_trades)) * 100 if len(sell_trades) > 0 else Decimal(0)

        avg_gain = winning_trades['realized_pnl_usd'].mean() if len(winning_trades) > 0 else Decimal(0)
        avg_loss = abs(losing_trades['realized_pnl_usd'].mean()) if len(losing_trades) > 0 else Decimal(0)
        payoff_ratio = avg_gain / avg_loss if avg_loss > 0 else Decimal('inf')

        open_positions = self.state_manager.get_open_positions()
        unrealized_pnl = sum(
            (Decimal(p.quantity) * self.mock_trader.get_current_price()) - Decimal(p.usd_value)
            for p in open_positions
        )

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

        btc_treasury_amount = treasury_trades['quantity'].sum()
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
