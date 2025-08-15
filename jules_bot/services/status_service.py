import logging
from jules_bot.database.postgres_manager import PostgresManager
from jules_bot.core_logic.strategy_rules import StrategyRules
from jules_bot.core.exchange_connector import ExchangeManager
from jules_bot.utils.config_manager import ConfigManager
from jules_bot.research.live_feature_calculator import LiveFeatureCalculator


logger = logging.getLogger(__name__)

def _calculate_progress_pct(current_price: float, start_price: float, target_price: float) -> float:
    """
    Calculates the percentage progress of a value from a starting point to a target.
    Clamps the result between 0 and 100.
    """
    if current_price is None or start_price is None or target_price is None:
        return 0.0

    # Avoid division by zero if start and target prices are the same.
    if target_price == start_price:
        return 100.0 if current_price >= target_price else 0.0

    # Calculate progress as a percentage. This works for both long and short scenarios.
    progress = (current_price - start_price) / (target_price - start_price) * 100

    # Clamp the result between 0% and 100%.
    return max(0, min(progress, 100))

class StatusService:
    def __init__(self, db_manager: PostgresManager, config_manager: ConfigManager, feature_calculator: LiveFeatureCalculator):
        self.db_manager = db_manager
        self.strategy = StrategyRules(config_manager)
        self.feature_calculator = feature_calculator
        # Note: ExchangeManager is instantiated per-request in get_extended_status
        # to ensure it's created with the correct mode (live/test).

    def get_extended_status(self, environment: str, bot_id: str):
        """
        Gathers and calculates extended status information, including
        open positions' PnL, progress towards sell targets, and buy signal readiness.
        """
        try:
            exchange_manager = ExchangeManager(mode=environment)
            symbol = "BTCUSDT" # Assuming BTCUSDT for now

            # 1. Fetch current market data with all features
            market_data_series = self.feature_calculator.get_current_candle_with_features()
            if market_data_series.empty:
                return {"error": "Could not fetch current market data."}

            market_data = market_data_series.to_dict()
            current_price = market_data.get('close', 0)

            # 2. Fetch open positions from local DB
            # CORRECTED LOGIC: Only filter by bot_id in 'backtest' mode.
            # For 'trade' and 'test' modes, we want to see all open positions for the environment.
            bot_id_to_filter = bot_id if environment == 'backtest' else None
            open_positions_db = self.db_manager.get_open_positions(environment, bot_id_to_filter)

            # 3. Process open positions
            positions_status = []
            for trade in open_positions_db:
                unrealized_pnl = self.strategy.calculate_net_unrealized_pnl(
                    entry_price=trade.price,
                    current_price=current_price,
                    total_quantity=trade.quantity
                ) if trade.price and trade.quantity else 0

                progress_to_sell_target_pct = _calculate_progress_pct(
                    current_price,
                    start_price=trade.price,
                    target_price=trade.sell_target_price
                )

                # Calculate how far the current price is from the sell target.
                price_to_target = 0
                if trade.sell_target_price is not None and current_price is not None:
                    price_to_target = trade.sell_target_price - current_price
                
                # Calculate the USD value of that price difference.
                usd_to_target = 0
                if trade.quantity is not None:
                    usd_to_target = price_to_target * trade.quantity

                positions_status.append({
                    "trade_id": trade.trade_id,
                    "entry_price": trade.price,
                    "current_price": current_price,
                    "quantity": trade.quantity,
                    "unrealized_pnl": unrealized_pnl,
                    "sell_target_price": trade.sell_target_price,
                    "progress_to_sell_target_pct": progress_to_sell_target_pct,
                    "price_to_target": price_to_target,
                    "usd_to_target": usd_to_target,
                })

            # 4. Determine buy signal status
            last_buy_price = None
            if open_positions_db:
                latest_position = sorted(open_positions_db, key=lambda p: p.timestamp, reverse=True)[0]
                last_buy_price = latest_position.price

            should_buy, _, reason = self.strategy.evaluate_buy_signal(
                market_data,
                open_positions=open_positions_db,
                last_buy_price=last_buy_price
            )

            # 5. Fetch trade history from DB
            trade_history = self.db_manager.get_all_trades_in_range(environment)
            trade_history_dicts = [trade.to_dict() for trade in trade_history]

            # 6. Fetch live wallet data
            wallet_balances = exchange_manager.get_account_balance()

            # Filter for relevant assets and calculate USD value
            relevant_assets = {'BTC', 'USDT'}
            processed_balances = []
            for bal in wallet_balances:
                asset = bal.get('asset')
                if asset in relevant_assets:
                    free = float(bal.get('free', 0))
                    locked = float(bal.get('locked', 0))
                    total = free + locked
                    
                    if asset == 'BTC':
                        bal['usd_value'] = total * current_price
                    elif asset == 'USDT':
                        bal['usd_value'] = total
                    
                    processed_balances.append(bal)

            # Calculate total wallet value in USD
            total_wallet_usd_value = sum(bal.get('usd_value', 0) for bal in processed_balances)

            # 7. DCOM Status Calculation
            dcom_status = self._calculate_dcom_status(
                wallet_balances=processed_balances,
                open_positions=positions_status,
                market_data=market_data,
                current_price=current_price
            )

            # 8. Assemble the final status object
            extended_status = {
                "mode": environment,
                "symbol": "BTC/USDT",
                "current_btc_price": current_price,
                "total_wallet_usd_value": total_wallet_usd_value,
                "open_positions_status": positions_status,
                "buy_signal_status": {
                    "should_buy": should_buy,
                    "reason": reason,
                },
                "dcom_status": dcom_status,
                "trade_history": trade_history_dicts,
                "wallet_balances": processed_balances
            }

            return extended_status

        except Exception as e:
            logger.error(f"Error getting extended status: {e}", exc_info=True)
            return {"error": str(e)}

    def _calculate_dcom_status(self, wallet_balances: list, open_positions: list, market_data: dict, current_price: float) -> dict:
        """
        Calculates all metrics for the Dynamic Capital & Opportunity Management module.
        """
        # Get DCOM parameters from strategy config
        dcom_rules = self.strategy.rules # Assuming rules are loaded in strategy
        wc_percent = float(dcom_rules.get('working_capital_percent', 0.6))
        ema_anchor_period = int(dcom_rules.get('ema_anchor_period', 200))
        initial_order_size = float(dcom_rules.get('initial_order_size_usd', 5.0))
        order_prog_factor = float(dcom_rules.get('order_progression_factor', 1.2))

        # 1. Equity Calculation
        cash_balance = float(next((bal.get('free', 0) for bal in wallet_balances if bal.get('asset') == 'USDT'), 0))

        # Calculate current market value of all open positions
        capital_in_use = sum(
            pos.get('quantity', 0) * current_price for pos in open_positions
        )

        total_equity = cash_balance + capital_in_use

        # 2. Strategic Split
        working_capital_target = total_equity * wc_percent
        strategic_reserve = total_equity - working_capital_target
        remaining_buying_power = working_capital_target - capital_in_use

        # 3. Market Anchor (Operating Mode)
        ema_anchor_key = f'ema_{ema_anchor_period}'
        ema_anchor_value = market_data.get(ema_anchor_key)

        operating_mode = "N/A"
        if ema_anchor_value is not None:
            if current_price > ema_anchor_value:
                operating_mode = "AGGRESSIVE"
            else:
                operating_mode = "CONSERVATIVE"

        # 4. Next Order Size Calculation
        num_open_positions = len(open_positions)
        next_order_size = initial_order_size * (order_prog_factor ** num_open_positions)

        return {
            "total_equity": total_equity,
            "working_capital_target": working_capital_target,
            "capital_in_use": capital_in_use,
            "remaining_buying_power": remaining_buying_power,
            "strategic_reserve": strategic_reserve,
            "operating_mode": operating_mode,
            "next_order_size_usd": next_order_size,
        }
