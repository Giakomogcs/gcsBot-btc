from jules_bot.utils.config_manager import ConfigManager

class StrategyRules:
    def __init__(self, config_manager: ConfigManager):
        self.rules = config_manager.get_section('STRATEGY_RULES')
        self.max_capital_per_trade_percent = float(self.rules.get('max_capital_per_trade_percent', 0.02))
        self.base_usd_per_trade = float(self.rules.get('base_usd_per_trade', 20.0))
        self.sell_factor = float(self.rules.get('sell_factor', 0.9))

    def evaluate_buy_signal(self, market_data: dict, open_positions_count: int) -> tuple[bool, str, str]:
        """
        Evaluates if a buy signal is present based on the market regime.
        Uses a more aggressive strategy if there are no open positions.
        Returns a tuple of (should_buy, regime, reason).
        """
        current_price = market_data.get('close')
        high_price = market_data.get('high')
        ema_100 = market_data.get('ema_100')
        ema_20 = market_data.get('ema_20')
        bbl = market_data.get('bbl_20_2_0')

        if any(v is None for v in [current_price, high_price, ema_100, ema_20, bbl]):
            return False, "unknown", "Not enough indicator data"

        # --- Aggressive Strategy for First Entry ---
        if open_positions_count == 0:
            if current_price > ema_100:
                # Aggressive uptrend entry: Buy if price is simply above the 20 EMA
                if current_price > ema_20:
                    return True, "uptrend", "Aggressive first entry (price > ema_20)"
            else:
                # Aggressive downtrend entry: Use existing volatility breakout signal
                if current_price <= bbl:
                    return True, "downtrend", "Aggressive first entry (volatility breakout)"

        # --- Standard Strategy for Subsequent Entries ---
        if current_price > ema_100:
            regime = "uptrend"
            # Standard Uptrend Logic: Wait for a pullback to the 20 EMA
            if high_price > ema_20 and current_price < ema_20:
                return True, regime, "Uptrend pullback"
        else:
            regime = "downtrend"
            # Standard Downtrend Logic: Volatility breakout
            if current_price <= bbl:
                return True, regime, "Downtrend volatility breakout"

        return False, "unknown", "No signal"

    def get_next_buy_amount(self, available_balance: float) -> float:
        """
        Calculates the USDT amount for the next purchase.
        """
        # Calculate trade size based on percentage of available capital
        capital_based_size = available_balance * self.max_capital_per_trade_percent

        # The trade size is the smaller of the base amount or the capital-based amount
        trade_size = min(self.base_usd_per_trade, capital_based_size)

        return trade_size

    def calculate_sell_target_price(self, purchase_price: float) -> float:
        """
        Calculates the target sell price based on the purchase price, commission,
        and target profit.
        """
        commission_rate = float(self.rules.get('commission_rate', 0.001))
        target_profit = float(self.rules.get('target_profit', 0.01))

        # Formula to calculate the price needed to break even, accounting for commissions on both buy and sell
        # P_sell * (1 - commission) = P_buy * (1 + commission)
        # P_sell_breakeven = P_buy * (1 + commission) / (1 - commission)
        numerator = purchase_price * (1 + commission_rate)
        denominator = (1 - commission_rate)

        if denominator == 0:
            return float('inf') # Avoid division by zero, return infinity

        break_even_price = numerator / denominator

        # Apply the target profit to the break-even price
        sell_target_price = break_even_price * (1 + target_profit)

        return sell_target_price

    def calculate_realized_pnl(self, buy_price: float, sell_price: float, quantity_sold: float) -> float:
        """
        Calculates the realized profit or loss from a trade, considering commissions.

        Args:
            buy_price (float): The price at which the asset was purchased.
            sell_price (float): The price at which the asset was sold.
            quantity_sold (float): The amount of the asset that was sold.

        Returns:
            float: The realized profit or loss in USD.
        """
        commission_rate = float(self.rules.get('commission_rate', 0.001))

        # Net Sales Revenue per unit = sell_price * (1 - commission_rate)
        # Proportional Purchase Cost per unit = buy_price * (1 + commission_rate)
        
        net_revenue_per_unit = sell_price * (1 - commission_rate)
        net_cost_per_unit = buy_price * (1 + commission_rate)
        
        profit_per_unit = net_revenue_per_unit - net_cost_per_unit
        
        realized_pnl = profit_per_unit * quantity_sold
        
        return realized_pnl

    def calculate_net_unrealized_pnl(self, entry_price: float, current_price: float, total_quantity: float) -> float:
        """
        Calculates the net unrealized PnL for an open position, factoring in
        the partial sale rule (90%) and commissions.

        Args:
            entry_price (float): The price at which the asset was purchased.
            current_price (float): The current market price of the asset.
            total_quantity (float): The total quantity of the asset held.

        Returns:
            float: The net unrealized profit or loss in USD.
        """
        # Calculate the PnL based on selling 90% of the position at the current price.
        quantity_to_sell = total_quantity * self.sell_factor
        
        # Reuse the realized PnL calculation with the current price as the sell price.
        net_unrealized_pnl = self.calculate_realized_pnl(
            buy_price=entry_price,
            sell_price=current_price,
            quantity_sold=quantity_to_sell
        )
        
        return net_unrealized_pnl
