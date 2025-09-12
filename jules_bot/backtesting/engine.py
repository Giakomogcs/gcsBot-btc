import logging
import uuid
import pandas as pd
import numpy as np
try:
    import optuna
except ImportError:
    optuna = None
import os
from datetime import timedelta
from decimal import Decimal, getcontext
from jules_bot.core.mock_exchange import MockTrader
from jules_bot.database.postgres_manager import PostgresManager
from jules_bot.utils.config_manager import config_manager
from jules_bot.core_logic.strategy_rules import StrategyRules
from jules_bot.core_logic.capital_manager import CapitalManager
from jules_bot.core_logic.dynamic_parameters import DynamicParameters
from jules_bot.bot.situational_awareness import SituationalAwareness
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from jules_bot.utils.logger import logger
from jules_bot.core.schemas import TradePoint
from jules_bot.research.feature_engineering import add_all_features
from jules_bot.services.trade_logger import TradeLogger

getcontext().prec = 28

class BacktestTrade:
    """A simple class to mimic the structure of a database Trade object for backtesting."""
    def __init__(self, **kwargs):
        self.timestamp = None
        self.order_type = None
        self.__dict__.update(kwargs)

    def to_dict(self):
        return self.__dict__

class Backtester:
    def __init__(self, db_manager: PostgresManager, days: int = None, start_date: str = None, end_date: str = None, config_manager=None, data: pd.DataFrame = None):
        if config_manager is None:
            from jules_bot.utils.config_manager import config_manager as global_config_manager
            config_manager = global_config_manager

        self.run_id = f"backtest_{uuid.uuid4()}"
        self.db_manager = db_manager
        self.trade_logger = TradeLogger(mode='backtest', db_manager=self.db_manager)
        symbol = config_manager.get('APP', 'symbol')

        if data is not None:
            logger.info(f"Initializing backtest run {self.run_id} with pre-loaded data ({len(data)} rows).")
            self.feature_data = data
            # Data is already processed, so we can skip fetching and feature calculation.
        else:
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
                raise ValueError("Backtester must be initialized with 'days' or 'start_date'/'end_date' if no data is provided.")

            logger.info(log_msg)
            price_data = self.db_manager.get_price_data(measurement=symbol, start_date=self.start_date_str, end_date=self.end_date_str)
            if price_data.empty:
                raise ValueError("No price data found for the specified period. Cannot run backtest.")

            logger.info("Calculating features for the entire backtest period...")
            features = add_all_features(price_data, live_mode=False).dropna()
            logger.info("Feature calculation complete.")

            logger.info("Initializing the Situational Awareness model...")
            sa_model = SituationalAwareness()
            self.feature_data = sa_model.transform(features)
            logger.info("Market regimes calculated for the entire backtest period.")

        # Common initialization logic
        initial_balance_str = config_manager.get('BACKTEST', 'initial_balance') or '1000.0'
        commission_fee_str = config_manager.get('STRATEGY_RULES', 'commission_rate') or '0.001'
        self.mock_trader = MockTrader(
            initial_balance_usd=Decimal(initial_balance_str),
            commission_fee_rate=Decimal(commission_fee_str),
            symbol=symbol
        )
        self.strategy_rules = StrategyRules(config_manager)
        self.capital_manager = CapitalManager(config_manager, self.strategy_rules, db_manager=self.db_manager)
        self.dynamic_params = DynamicParameters(config_manager)

    def run(self, trial: 'optuna.Trial' = None, return_full_results: bool = False):
        logger.info(f"--- Starting backtest run {self.run_id} ---")

        strategy_rules = self.strategy_rules
        symbol = config_manager.get('APP', 'symbol')
        strategy_name = config_manager.get('APP', 'strategy_name', fallback='default_strategy')
        min_trade_size = Decimal(config_manager.get('TRADING_STRATEGY', 'min_trade_size_usdt', fallback='10.0'))

        open_positions = {}
        portfolio_history = []
        all_trades_for_run = []

        # Define a pruning frequency to avoid checking on every single candle
        pruning_frequency = 1000  # Check every 1000 candles (approx. 16 hours of 1m data)

        for i, (current_time, candle) in enumerate(self.feature_data.iterrows()):
            current_price = Decimal(str(candle['close']))
            self.mock_trader.set_current_time_and_price(current_time, current_price)

            current_regime = candle.get('market_regime', -1)
            self.dynamic_params.update_parameters(int(current_regime))
            current_params = self.dynamic_params.parameters

            cash_balance = self.mock_trader.get_account_balance()
            current_open_positions_value = sum(pos['quantity'] * current_price for pos in open_positions.values())
            total_portfolio_value = cash_balance + current_open_positions_value
            portfolio_history.append(total_portfolio_value)

            # --- Pruning Check ---
            if trial and i > 0 and i % pruning_frequency == 0:
                trial.report(float(total_portfolio_value), i)
                if trial.should_prune():
                    # If the trial is unpromising, Optuna will tell us to stop early.
                    if optuna:
                        raise optuna.TrialPruned()

            positions_to_sell_now = []
            for trade_id, position in list(open_positions.items()):
                sell_target_price = position.get('sell_target_price', Decimal('inf'))
                if current_price >= sell_target_price:
                    positions_to_sell_now.append(position)
                    continue

                entry_price = position['price']

                # Calculate the current net unrealized PnL for the position
                net_unrealized_pnl = self.strategy_rules.calculate_net_unrealized_pnl(
                    entry_price=entry_price,
                    current_price=current_price,
                    total_quantity=position['quantity'],
                    buy_commission_usd=position.get('commission_usd', Decimal('0'))
                )

                # --- Unified Smart Trailing Stop Logic ---
                decision, reason, new_trail_percentage = self.strategy_rules.evaluate_smart_trailing_stop(
                    position, net_unrealized_pnl
                )

                if decision == "ACTIVATE":
                    logger.info(f"🚀 Backtest: {reason}")
                    position['is_smart_trailing_active'] = True
                    position['smart_trailing_highest_profit'] = net_unrealized_pnl
                
                elif decision == "DEACTIVATE":
                    logger.warning(f"🟡 Backtest: {reason}")
                    position['is_smart_trailing_active'] = False
                    position['smart_trailing_highest_profit'] = None
                    position['current_trail_percentage'] = None

                elif decision == "UPDATE_PEAK":
                    logger.info(f"📈 Backtest: {reason}")
                    position['smart_trailing_highest_profit'] = net_unrealized_pnl
                    if new_trail_percentage:
                        position['current_trail_percentage'] = new_trail_percentage

                elif decision == "SELL":
                    # --- UNIFIED PROFITABILITY GATE ---
                    # This check is crucial and mimics the live bot's final safety net.
                    break_even_price = self.strategy_rules.calculate_break_even_price(position['price'])
                    if current_price > break_even_price:
                        logger.info(f"✅ Backtest: {reason}. Position is profitable, marking for sale.")
                        positions_to_sell_now.append(position)
                    else:
                        logger.warning(
                            f"❌ Backtest: SALE CANCELED for position {trade_id}. Reason: {reason}. "
                            f"Current price ${current_price:,.2f} is not above break-even price ${break_even_price:,.2f}."
                        )
                        # Reset the trailing stop to prevent a loss-making sale on the next tick.
                        position['is_smart_trailing_active'] = False
                        position['smart_trailing_highest_profit'] = None

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
                            'trade_id': trade_id, 'linked_trade_id': trade_id, # Link sell to buy
                            'exchange': "backtest_engine", 'order_type': "sell",
                            'status': "CLOSED", 'price': sell_result['price'], 'quantity': sell_result['quantity'],
                            'usd_value': sell_result['usd_value'], 'commission': sell_result.get('commission_usd', Decimal('0')),
                            'commission_asset': "USDT", 'timestamp': current_time, 'decision_context': candle.to_dict(),
                            'commission_usd': sell_result.get('commission_usd', Decimal('0')), 'realized_pnl_usd': realized_pnl_usd
                        }
                        all_trades_for_run.append(BacktestTrade(**trade_data))
                        del open_positions[trade_id]

            # BUY LOGIC
            market_data = candle.to_dict()
            # Filter trade history to match the live bot's rolling window for difficulty calculation.
            timeout_hours = self.capital_manager.difficulty_reset_timeout_hours
            start_date_for_difficulty = current_time - timedelta(hours=timeout_hours)
            
            recent_trades_for_difficulty = [
                t for t in all_trades_for_run 
                if t.timestamp and t.timestamp >= start_date_for_difficulty
            ]

            buy_amount_usdt, op_mode, reason, _, diff_factor = self.capital_manager.get_buy_order_details(
                market_data=market_data, open_positions=list(open_positions.values()),
                portfolio_value=total_portfolio_value, free_cash=cash_balance,
                params=current_params, trade_history=recent_trades_for_difficulty,
                current_time=current_time
            )

            if buy_amount_usdt > 0 and cash_balance >= min_trade_size:
                decision_context_buy = {**candle.to_dict(), 'operating_mode': op_mode, 'buy_trigger_reason': reason, 'market_regime': current_regime}
                success, buy_result = self.mock_trader.execute_buy(buy_amount_usdt, self.run_id, decision_context_buy)
                if success:
                    new_trade_id = str(uuid.uuid4())
                    sell_target_price = strategy_rules.calculate_sell_target_price(buy_result['price'], buy_result['quantity'], params=current_params)

                    position_data = {
                        'trade_id': new_trade_id,
                        'price': buy_result['price'],
                        'quantity': buy_result['quantity'],
                        'usd_value': buy_result['usd_value'],
                        'sell_target_price': sell_target_price,
                        'commission_usd': buy_result.get('commission_usd', Decimal('0')),
                        # State for the new unified smart trailing logic
                        'is_smart_trailing_active': False,
                        'smart_trailing_highest_profit': None,
                        'activation_price': None,
                        'current_trail_percentage': None,
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
                    all_trades_for_run.append(BacktestTrade(**trade_data))

        self._log_trades_to_db(all_trades_for_run)
        results = self._generate_and_save_summary(open_positions, portfolio_history)
        logger.info(f"--- Backtest {self.run_id} finished ---")

        if return_full_results:
            return results
        else:
            # For backward compatibility with the old optimizer, return only the final balance as a float.
            final_balance = results.get("final_balance", Decimal("0.0"))
            return float(final_balance)

    def _log_trades_to_db(self, trades: list):
        """
        Logs the list of completed trades from the backtest simulation to the database.
        It correctly handles creating BUY records and updating them for SELLs.
        """
        if not trades:
            return
        logger.info(f"Logging {len(trades)} trades from backtest run to database...")
        for trade in trades:
            trade_data = trade.to_dict()  # Convert BacktestTrade object to dictionary

            if trade_data.get('order_type') == 'buy':
                # This is a new position, so we create a new record.
                self.trade_logger.log_trade(trade_data)
            elif trade_data.get('order_type') == 'sell':
                # This is a closing trade, so we update the original record.
                # The `update_trade` method in the logger handles the data mapping.
                self.trade_logger.update_trade(trade_data)
            else:
                logger.warning(f"Unknown order type in backtest log: {trade_data.get('order_type')}")

    def _display_results_table(self, results: dict):
        """
        Uses the rich library to display backtest results in a clean, formatted table.
        """
        console = Console()

        # Helper to format values
        def format_value(value, type):
            if value is None or (isinstance(value, Decimal) and not value.is_finite()):
                return "[dim]---[/dim]"
            if type == 'money':
                return f"${value:,.2f}"
            if type == 'percent':
                style = "bold green" if value > 0 else "bold red" if value < 0 else "default"
                return f"[{style}]{value:.2f}%[/{style}]"
            if type == 'percent_dd':
                return f"{value * 100:.2f}%"
            if type == 'ratio':
                return f"{value:.2f}"
            if type == 'string':
                return str(value)
            if type == 'integer':
                return str(value)
            return str(value)

        # --- Header Panel ---
        if not self.feature_data.empty:
            start_date = self.feature_data.index[0].date()
            end_date = self.feature_data.index[-1].date()
            header_text = f"Period: [bold]{start_date}[/] to [bold]{end_date}[/]\nRun ID: [dim]{self.run_id}[/dim]"
        else:
            header_text = f"Run ID: [dim]{self.run_id}[/dim]"

        console.print(Panel(header_text, title="[bold cyan]Backtest Results[/bold cyan]", expand=False))

        # --- Main Tables ---
        perf_table = Table(title="[bold]Performance Summary[/bold]", show_header=False, box=None, padding=(0, 2))
        perf_table.add_column(style="cyan")
        perf_table.add_column(style="bold", justify="right")

        trade_table = Table(title="[bold]Trade Analysis[/bold]", show_header=False, box=None, padding=(0, 2))
        trade_table.add_column(style="cyan")
        trade_table.add_column(style="bold", justify="right")

        risk_table = Table(title="[bold]Risk & Return Analysis[/bold]", show_header=False, box=None, padding=(0, 2))
        risk_table.add_column(style="cyan")
        risk_table.add_column(style="bold", justify="right")

        # --- Populating Data ---
        # Performance
        pnl_style = "bold green" if results['net_pnl_usd'] > 0 else "bold red" if results['net_pnl_usd'] < 0 else "default"
        perf_table.add_row("Initial Balance", format_value(results['initial_balance'], 'money'))
        perf_table.add_row("Final Cash Balance", format_value(results.get('final_cash_balance'), 'money'))
        perf_table.add_row("Open Positions Value", format_value(results.get('final_open_positions_value'), 'money'))
        perf_table.add_row("Final Total Balance", format_value(results['final_balance'], 'money'))
        perf_table.add_row("Net PnL", f"[{pnl_style}]{format_value(results['net_pnl_usd'], 'money')} ({format_value(results['net_pnl_pct'], 'percent')})[/{pnl_style}]")
        perf_table.add_row("Total Realized PnL", format_value(results['total_realized_pnl'], 'money'))

        # Trades
        profit_factor = results['profit_factor']
        if profit_factor.is_infinite():
            profit_factor_str = "[bold green]∞ (No Losses)[/bold green]"
        else:
            profit_factor_str = format_value(profit_factor, 'ratio')

        duration_sec = results['avg_trade_duration_seconds']
        if duration_sec > 0:
            days, remainder = divmod(duration_sec, 86400)
            hours, remainder = divmod(remainder, 3600)
            minutes, _ = divmod(remainder, 60)
            duration_str = f"{int(days)}d {int(hours)}h {int(minutes)}m"
        else:
            duration_str = "[dim]---[/dim]"

        trade_table.add_row("Total Buy Trades", format_value(results['buy_trades_count'], 'integer'))
        trade_table.add_row("Total Sell Trades", format_value(results['sell_trades_count'], 'integer'))
        trade_table.add_row("Win Rate", format_value(results['win_rate'], 'percent'))
        trade_table.add_row("Profit Factor", profit_factor_str)
        trade_table.add_row("Avg. Gain %", format_value(results['avg_gain_pct'], 'percent'))
        trade_table.add_row("Avg. Loss %", format_value(results['avg_loss_pct'], 'percent'))
        trade_table.add_row("Avg. Trade Duration", duration_str)
        trade_table.add_row("Total Fees Paid", format_value(results['total_fees_usd'], 'money'))

        # Risk
        risk_table.add_row("Max Drawdown", format_value(results['max_drawdown'], 'percent_dd'))
        risk_table.add_row("Sharpe Ratio (Ann.)", format_value(results['sharpe_ratio'], 'ratio'))
        risk_table.add_row("Sortino Ratio (Ann.)", format_value(results['sortino_ratio'], 'ratio'))
        risk_table.add_row("Calmar Ratio (Ann.)", format_value(results['calmar_ratio'], 'ratio'))

        # --- Print Tables ---
        console.print(perf_table)
        console.print(trade_table)
        console.print(risk_table)

    def _generate_and_save_summary(self, open_positions: dict, portfolio_history: list[Decimal]):
        logger.info("--- Generating backtest summary ---")

        all_trades_for_run = self.db_manager.get_trades_by_run_id(self.run_id)
        
        if not all_trades_for_run:
            logger.warning("No trades were executed in this backtest run.")
            all_trades_df = pd.DataFrame()
        else:
            all_trades_df = pd.DataFrame([t.to_dict() for t in all_trades_for_run])
            numeric_cols = ['price', 'quantity', 'usd_value', 'commission', 'commission_usd', 'realized_pnl_usd', 'hodl_asset_amount', 'hodl_asset_value_at_sell']
            for col in numeric_cols:
                if col in all_trades_df.columns:
                    all_trades_df[col] = all_trades_df[col].apply(lambda x: Decimal(str(x)) if pd.notna(x) else Decimal(0))

        # --- Basic Performance ---
        initial_balance = self.mock_trader.initial_balance
        final_balance = self.mock_trader.get_total_portfolio_value()
        net_pnl = final_balance - initial_balance
        net_pnl_percent = (net_pnl / initial_balance) * 100 if initial_balance > 0 else Decimal(0)

        # --- Trade Analysis ---
        total_realized_pnl = Decimal(0)
        total_fees_usd = Decimal(0)
        win_rate = Decimal(0)
        avg_gain_pct = Decimal(0)
        avg_loss_pct = Decimal(0)
        buy_trades_count = 0
        sell_trades_count = 0
        avg_trade_duration = timedelta(0)
        profit_factor = Decimal(0)

        if not all_trades_df.empty:
            sell_trades = all_trades_df[all_trades_df['status'] == 'CLOSED'].copy()
            buy_trades = all_trades_df[all_trades_df['order_type'] == 'buy'].copy()
            buy_trades_count = len(buy_trades)
            sell_trades_count = len(sell_trades)

            total_fees_usd = all_trades_df['commission_usd'].sum()

            if sell_trades_count > 0:
                total_realized_pnl = sell_trades['realized_pnl_usd'].sum()
                winning_trades = sell_trades[sell_trades['realized_pnl_usd'] > 0]
                losing_trades = sell_trades[sell_trades['realized_pnl_usd'] < 0]

                win_rate = (Decimal(len(winning_trades)) / Decimal(sell_trades_count)) * 100 if sell_trades_count > 0 else Decimal(0)

                merged_trades = pd.merge(
                    sell_trades,
                    buy_trades,
                    left_on='linked_trade_id',
                    right_on='trade_id',
                    suffixes=('_sell', '_buy')
                )

                if not merged_trades.empty:
                    merged_trades['timestamp_sell'] = pd.to_datetime(merged_trades['timestamp_sell'])
                    merged_trades['timestamp_buy'] = pd.to_datetime(merged_trades['timestamp_buy'])
                    durations = merged_trades['timestamp_sell'] - merged_trades['timestamp_buy']
                    avg_trade_duration = durations.mean() if not durations.empty else timedelta(0)

                    merged_trades['pnl_pct'] = merged_trades.apply(
                        lambda row: (row['realized_pnl_usd_sell'] / row['usd_value_buy']) * 100 if row['usd_value_buy'] > 0 else Decimal(0), axis=1
                    )

                    gaining_trades_pct = merged_trades[merged_trades['pnl_pct'] > 0]['pnl_pct']
                    losing_trades_pct = merged_trades[merged_trades['pnl_pct'] < 0]['pnl_pct']

                    avg_gain_pct = Decimal(gaining_trades_pct.mean()) if not gaining_trades_pct.empty else Decimal(0)
                    avg_loss_pct = abs(Decimal(losing_trades_pct.mean())) if not losing_trades_pct.empty else Decimal(0)


                gross_profit = winning_trades['realized_pnl_usd'].sum()
                gross_loss = abs(losing_trades['realized_pnl_usd'].sum())
                profit_factor = gross_profit / gross_loss if gross_loss > 0 else Decimal('inf')

        # --- Risk and Return Analysis ---
        max_drawdown = Decimal(0)
        sharpe_ratio = Decimal(0)
        sortino_ratio = Decimal(0)
        calmar_ratio = Decimal(0)

        if portfolio_history and len(portfolio_history) > 1:
            # Create the DataFrame with the correct DatetimeIndex from the start
            portfolio_df = pd.DataFrame(
                portfolio_history,
                columns=['value'],
                index=self.feature_data.index[:len(portfolio_history)]
            )
            portfolio_float = portfolio_df['value'].astype(float)

            # Max Drawdown
            peak = portfolio_float.expanding(min_periods=1).max()
            drawdown = (portfolio_float - peak) / peak
            max_drawdown = Decimal(str(abs(drawdown.min()))) if not drawdown.empty else Decimal(0)

            # Ratios
            # Now that the DataFrame has a DatetimeIndex, we can resample directly
            daily_returns = portfolio_float.resample('D').last().pct_change().dropna()

            if not daily_returns.empty:
                try:
                    std_dev = daily_returns.std()
                    if std_dev != 0:
                        sharpe_ratio = Decimal(str(np.sqrt(365) * daily_returns.mean() / std_dev))
                except (ValueError, TypeError):
                    sharpe_ratio = Decimal(0)

                try:
                    downside_returns = daily_returns[daily_returns < 0]
                    if not downside_returns.empty:
                        downside_std = downside_returns.std()
                        if downside_std != 0 and not np.isnan(downside_std):
                            sortino_ratio = Decimal(str(np.sqrt(365) * daily_returns.mean() / downside_std))
                except (ValueError, TypeError):
                    sortino_ratio = Decimal(0)

            try:
                if max_drawdown > 0:
                    total_days = (self.feature_data.index[-1] - self.feature_data.index[0]).days
                    if total_days > 0:
                        annualized_return = (final_balance / initial_balance) ** (Decimal('365.0') / Decimal(total_days)) - 1
                        calmar_ratio = annualized_return / max_drawdown
            except (ZeroDivisionError, ValueError, TypeError):
                calmar_ratio = Decimal(0)

        final_cash_balance = self.mock_trader.balance_usd
        final_open_positions_value = final_balance - final_cash_balance

        results = {
            "initial_balance": initial_balance,
            "final_balance": final_balance,
            "final_cash_balance": final_cash_balance,
            "final_open_positions_value": final_open_positions_value,
            "net_pnl_usd": net_pnl,
            "net_pnl_pct": net_pnl_percent,
            "total_realized_pnl": total_realized_pnl,
            "buy_trades_count": buy_trades_count,
            "sell_trades_count": sell_trades_count,
            "win_rate": win_rate,
            "profit_factor": profit_factor,
            "avg_gain_pct": avg_gain_pct,
            "avg_loss_pct": avg_loss_pct,
            "avg_trade_duration_seconds": avg_trade_duration.total_seconds() if pd.notna(avg_trade_duration) else 0,
            "total_fees_usd": total_fees_usd,
            "max_drawdown": max_drawdown,
            "sharpe_ratio": sharpe_ratio,
            "sortino_ratio": sortino_ratio,
            "calmar_ratio": calmar_ratio,
        }

        # Display the results in a clean table format
        self._display_results_table(results)

        return results

def trade_point_to_dict(self):
    from dataclasses import asdict
    return asdict(self)
TradePoint.to_dict = trade_point_to_dict
