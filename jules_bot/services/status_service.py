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

    def _calculate_dcom_equity(self, exchange_manager: ExchangeManager, open_positions: list, current_price: float) -> dict:
        """
        Calculates the total equity and its components based on the DCOM strategy.
        """
        try:
            # 1. Get current cash balance (USD)
            cash_balance = exchange_manager.get_usdt_balance()

            # 2. Get open positions and their current market value
            capital_in_use = sum(
                float(p.quantity) * current_price for p in open_positions
            )

            # 3. Calculate Total Equity
            total_equity = cash_balance + capital_in_use

            return {
                "total_equity": total_equity,
                "cash_balance": cash_balance,
                "capital_in_use": capital_in_use
            }
        except Exception as e:
            logger.error(f"Failed to calculate DCOM equity in StatusService: {e}", exc_info=True)
            return {
                "total_equity": 0,
                "cash_balance": 0,
                "capital_in_use": 0
            }

    def get_extended_status(self, environment: str, bot_id: str):
        """
        Gathers and calculates extended status information, including DCOM metrics.
        """
        try:
            exchange_manager = ExchangeManager(mode=environment)
            symbol = "BTCUSDT"

            # 1. Fetch market data
            market_data_series = self.feature_calculator.get_current_candle_with_features()
            if market_data_series.empty:
                return {"error": "Could not fetch current market data."}
            market_data = market_data_series.to_dict()
            current_price = market_data.get('close', 0)

            # 2. Fetch open positions
            bot_id_to_filter = bot_id if environment == 'backtest' else None
            open_positions_db = self.db_manager.get_open_positions(environment, bot_id_to_filter)

            # 3. Calculate DCOM Equity and Capital Allocation
            equity_data = self._calculate_dcom_equity(exchange_manager, open_positions_db, current_price)
            total_equity = equity_data['total_equity']
            capital_in_use = equity_data['capital_in_use']
            working_capital = total_equity * self.strategy.working_capital_percent
            strategic_reserve = total_equity - working_capital
            remaining_buying_power = working_capital - capital_in_use

            # 4. Determine DCOM Operating Mode
            ema_anchor_key = f'ema_{self.strategy.ema_anchor_period}'
            ema_anchor_value = market_data.get(ema_anchor_key)
            operating_mode = "N/A"
            if ema_anchor_value:
                operating_mode, _ = self.strategy.get_operating_mode(current_price, ema_anchor_value)

            # 5. Calculate Next Order Size
            next_order_size = self.strategy.calculate_next_order_size(len(open_positions_db))

            dcom_status = {
                "total_equity": total_equity,
                "working_capital_target": working_capital,
                "working_capital_in_use": capital_in_use,
                "working_capital_remaining": remaining_buying_power,
                "strategic_reserve": strategic_reserve,
                "operating_mode": operating_mode,
                "next_order_size": next_order_size
            }

            # 6. Process open positions (for PnL, etc.)
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
                price_to_target = 0
                if trade.sell_target_price is not None and current_price is not None:
                    price_to_target = trade.sell_target_price - current_price
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

            # 7. Fetch other data (trade history, wallet balances)
            trade_history = self.db_manager.get_all_trades_in_range(environment)
            trade_history_dicts = [trade.to_dict() for trade in trade_history]
            wallet_balances = exchange_manager.get_account_balance()
            
            processed_balances = []
            for bal in wallet_balances:
                asset = bal.get('asset')
                free = float(bal.get('free', 0))
                locked = float(bal.get('locked', 0))
                total = free + locked
                if total > 0:
                    if asset == 'BTC':
                        bal['usd_value'] = total * current_price
                    elif asset == 'USDT':
                        bal['usd_value'] = total
                    processed_balances.append(bal)

            total_wallet_usd_value = sum(bal.get('usd_value', 0) for bal in processed_balances)

            # 8. Assemble final status object
            extended_status = {
                "mode": environment,
                "symbol": "BTC/USDT",
                "current_btc_price": current_price,
                "total_wallet_usd_value": total_wallet_usd_value,
                "open_positions_status": positions_status,
                "trade_history": trade_history_dicts,
                "wallet_balances": processed_balances,
                "dcom_status": dcom_status,
                "buy_signal_status": {} 
            }

            return extended_status

        except Exception as e:
            logger.error(f"Error getting extended status: {e}", exc_info=True)
            return {"error": str(e)}

    def _calculate_buy_progress(self, market_data: dict, open_positions_count: int) -> tuple[float, float]:
        """
        Calculates the target price for the next buy and the progress towards it.
        """
        current_price = market_data.get('close')
        ema_20 = market_data.get('ema_20')
        bbl = market_data.get('bbl_20_2_0')
        ema_100 = market_data.get('ema_100')

        if any(v is None for v in [current_price, ema_20, bbl, ema_100]):
            return 0, 0

        if open_positions_count == 0:
            if current_price > ema_100: # Uptrend
                target_price = ema_20
                progress = 100.0 if current_price > target_price else \
                           _calculate_progress_pct(current_price, current_price * 1.05, target_price)
            else: # Downtrend
                target_price = bbl
                progress = _calculate_progress_pct(current_price, market_data.get('high', current_price), target_price)
            return target_price, progress

        if current_price > ema_100: # Uptrend pullback
            target_price = ema_20
            progress = _calculate_progress_pct(current_price, market_data.get('high', current_price), target_price)
        else: # Downtrend breakout
            target_price = bbl
            progress = _calculate_progress_pct(current_price, market_data.get('high', current_price), target_price)

        return target_price, progress
