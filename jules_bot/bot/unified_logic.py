import time
from decimal import Decimal, getcontext
from datetime import datetime, timedelta
from jules_bot.utils.logger import logger
from jules_bot.utils.config_manager import config_manager
from jules_bot.core_logic.state_manager import StateManager
from jules_bot.core_logic.trader import Trader
from jules_bot.core_logic.strategy_rules import StrategyRules
from jules_bot.core_logic.capital_manager import CapitalManager
from jules_bot.core_logic.dynamic_parameters import DynamicParameters
from jules_bot.bot.situational_awareness import SituationalAwareness
from jules_bot.database.postgres_manager import PostgresManager

getcontext().prec = 28

class UnifiedTradingLogic:
    def __init__(
        self,
        bot_id: str,
        mode: str,
        trader: Trader,
        state_manager: StateManager,
        capital_manager: CapitalManager,
        strategy_rules: StrategyRules,
        dynamic_params: DynamicParameters,
        sa_instance: SituationalAwareness,
        portfolio_manager,
        db_manager: PostgresManager,
        account_manager = None # Optional, only for live mode
    ):
        self.bot_id = bot_id
        self.mode = mode
        self.trader = trader
        self.state_manager = state_manager
        self.capital_manager = capital_manager
        self.strategy_rules = strategy_rules
        self.dynamic_params = dynamic_params
        self.sa_instance = sa_instance
        self.portfolio_manager = portfolio_manager
        self.db_manager = db_manager
        self.account_manager = account_manager
        self.symbol = config_manager.get('APP', 'symbol')
        self.min_trade_size = Decimal(config_manager.get('TRADING_STRATEGY', 'min_trade_size_usdt', fallback='10.0'))

        self.is_monitoring_for_reversal = False
        self.lowest_price_since_monitoring_started = None
        self.monitoring_started_at = None
        self.reversal_buy_threshold_percent = Decimal(config_manager.get('STRATEGY_RULES', 'reversal_buy_threshold_percent', fallback='0.005'))
        self.reversal_monitoring_timeout_seconds = int(config_manager.get('STRATEGY_RULES', 'reversal_monitoring_timeout_seconds', fallback='300'))

        self.last_decision_reason: str = "Initializing..."
        self.last_operating_mode: str = "STARTUP"
        self.last_difficulty_factor: Decimal = Decimal('0')

    def run_trading_cycle(self, features_df):
        logger.info("--- Starting new unified trading cycle ---")
        self.state_manager.recalculate_open_position_targets(self.strategy_rules, self.sa_instance, self.dynamic_params)

        if features_df.empty:
            logger.warning("Feature dataframe is empty. Skipping cycle.")
            return None, None # Return None to signal no status update

        final_candle = features_df.iloc[-1]
        if final_candle.isnull().any():
            logger.warning(f"Final candle contains NaN values, skipping cycle. Data: {final_candle.to_dict()}")
            return None, None

        current_price = Decimal(final_candle['close'])
        total_portfolio_value = self.portfolio_manager.get_total_portfolio_value(current_price)

        current_regime = -1
        if self.sa_instance:
            try:
                regime_df = self.sa_instance.transform(features_df)
                if not regime_df.empty:
                    current_regime = int(regime_df['market_regime'].iloc[-1])
            except Exception as e:
                logger.error(f"Error getting market regime: {e}", exc_info=True)

        if current_regime == -1:
            logger.warning("Market regime is -1. Skipping buy/sell logic.")
            # Return a full 5-item tuple to avoid unpacking errors downstream
            return "Regime is -1", "SKIPPED", Decimal('0'), current_regime, total_portfolio_value

        self.dynamic_params.update_parameters(current_regime)
        current_params = self.dynamic_params.parameters
        open_positions = self.state_manager.get_open_positions()
        base_asset = self.symbol.replace("USDT", "")
        
        cash_balance = Decimal(self.trader.get_account_balance(asset="USDT"))

        end_date = datetime.utcnow()
        start_date = end_date - timedelta(hours=self.capital_manager.difficulty_reset_timeout_hours)
        trade_history = self.db_manager.get_all_trades_in_range(
            mode=self.mode, start_date=start_date, end_date=end_date, bot_id=self.bot_id
        )

        sell_candidates = []
        for position in open_positions:
            sell_target_price = Decimal(str(position.sell_target_price)) if position.sell_target_price is not None else Decimal('inf')
            if current_price >= sell_target_price:
                sell_candidates.append((position, "take_profit"))
                continue

            entry_price = Decimal(str(position.price))
            net_unrealized_pnl = self.strategy_rules.calculate_net_unrealized_pnl(
                entry_price=entry_price, current_price=current_price,
                total_quantity=Decimal(str(position.quantity)),
                buy_commission_usd=Decimal(str(position.commission_usd or '0'))
            )
            min_profit_target = self.strategy_rules.trailing_stop_profit

            if not position.is_smart_trailing_active and net_unrealized_pnl >= min_profit_target:
                self.state_manager.update_trade_smart_trailing_state(
                    trade_id=position.trade_id, is_active=True,
                    highest_profit=net_unrealized_pnl, activation_price=current_price
                )
                position.is_smart_trailing_active = True
                position.smart_trailing_highest_profit = net_unrealized_pnl
                continue

            if position.is_smart_trailing_active:
                highest_profit = Decimal(str(position.smart_trailing_highest_profit)) if position.smart_trailing_highest_profit is not None else net_unrealized_pnl
                if net_unrealized_pnl < 0:
                    self.state_manager.update_trade_smart_trailing_state(
                        trade_id=position.trade_id, is_active=False, highest_profit=None, activation_price=None
                    )
                    position.is_smart_trailing_active = False
                    continue
                if net_unrealized_pnl > highest_profit:
                    self.state_manager.update_trade_smart_trailing_state(trade_id=position.trade_id, is_active=True, highest_profit=net_unrealized_pnl)
                    position.smart_trailing_highest_profit = net_unrealized_pnl
                    highest_profit = net_unrealized_pnl
                
                trail_percentage = self.strategy_rules.dynamic_trail_percentage
                stop_profit_level = highest_profit * (Decimal('1') - trail_percentage)
                final_trigger_profit = max(stop_profit_level, min_profit_target)

                if net_unrealized_pnl <= final_trigger_profit:
                    sell_candidates.append((position, "trailing_stop"))

        sell_executed_in_cycle = False
        positions_to_sell_now = []
        if sell_candidates:
            for position, reason in sell_candidates:
                entry_price = Decimal(str(position.price))
                break_even_price = self.strategy_rules.calculate_break_even_price(entry_price)
                if current_price > break_even_price:
                    positions_to_sell_now.append(position)
                elif reason == 'trailing_stop' and position.is_smart_trailing_active:
                    self.state_manager.update_trade_smart_trailing_state(
                        trade_id=position.trade_id, is_active=False, highest_profit=None, activation_price=None
                    )
                    position.is_smart_trailing_active = False
        
        if positions_to_sell_now:
            total_sell_quantity = sum(Decimal(str(p.quantity)) * self.strategy_rules.sell_factor for p in positions_to_sell_now)
            available_balance = Decimal(self.trader.get_account_balance(asset=base_asset))
            if total_sell_quantity <= available_balance:
                for position in positions_to_sell_now:
                    sell_position_data = position.to_dict()
                    sell_position_data['quantity'] = Decimal(str(position.quantity)) * self.strategy_rules.sell_factor
                    success, sell_result = self.trader.execute_sell(sell_position_data, self.bot_id, final_candle.to_dict())
                    if success:
                        sell_executed_in_cycle = True
                        pnl = self.strategy_rules.calculate_realized_pnl(
                            buy_price=Decimal(str(position.price)), sell_price=Decimal(str(sell_result.get('price'))),
                            quantity_sold=sell_position_data['quantity'],
                            buy_commission_usd=Decimal(str(position.commission_usd or '0')),
                            sell_commission_usd=Decimal(str(sell_result.get('commission_usd', '0'))),
                            buy_quantity=Decimal(str(position.quantity))
                        )
                        sell_result.update({"realized_pnl_usd": pnl})
                        self.state_manager.close_forced_position(position.trade_id, sell_result, pnl) # Simplified for now
                        self.portfolio_manager.get_total_portfolio_value(current_price, force_recalculation=True)

        if sell_executed_in_cycle:
            trade_history = self.db_manager.get_all_trades_in_range(
                mode=self.mode, start_date=start_date, end_date=end_date, bot_id=self.bot_id
            )

        market_data = final_candle.to_dict()
        buy_from_reversal = False

        if self.is_monitoring_for_reversal:
            if time.time() - self.monitoring_started_at > self.reversal_monitoring_timeout_seconds:
                self.is_monitoring_for_reversal = False
            elif current_price < self.lowest_price_since_monitoring_started:
                self.lowest_price_since_monitoring_started = current_price
                self.monitoring_started_at = time.time()
            elif current_price >= self.lowest_price_since_monitoring_started * (1 + self.reversal_buy_threshold_percent):
                buy_from_reversal = True
                self.is_monitoring_for_reversal = False

        buy_amount_usdt, op_mode, reason, regime, diff_factor = self.capital_manager.get_buy_order_details(
            market_data=market_data, open_positions=open_positions, portfolio_value=total_portfolio_value,
            free_cash=cash_balance, params=current_params, trade_history=trade_history,
            force_buy_signal=buy_from_reversal, forced_reason="Buy triggered by price reversal."
        )
        self.last_decision_reason, self.last_operating_mode, self.last_difficulty_factor = reason, op_mode, diff_factor

        if regime == "START_MONITORING" and not self.is_monitoring_for_reversal:
            self.is_monitoring_for_reversal = True
            self.lowest_price_since_monitoring_started = current_price
            self.monitoring_started_at = time.time()

        elif buy_amount_usdt > 0 and buy_amount_usdt >= self.min_trade_size:
            decision_context = {"operating_mode": op_mode, "buy_trigger_reason": reason, "market_regime": int(current_regime)}
            success, buy_result = self.trader.execute_buy(buy_amount_usdt, self.bot_id, decision_context)
            if success:
                sell_target_price = self.strategy_rules.calculate_sell_target_price(
                    Decimal(str(buy_result.get('price'))), Decimal(str(buy_result.get('quantity'))), params=current_params
                )
                self.state_manager.create_new_position(buy_result, sell_target_price)
                self.portfolio_manager.get_total_portfolio_value(Decimal(str(buy_result.get('price'))), force_recalculation=True)
        
        return self.last_decision_reason, self.last_operating_mode, self.last_difficulty_factor, current_regime, total_portfolio_value
