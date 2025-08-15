from jules_bot.utils.config_manager import ConfigManager

class StrategyRules:
    def __init__(self, config_manager: ConfigManager):
        self.rules = config_manager.get_section('STRATEGY_RULES')

        # Sell logic (unchanged)
        self.sell_factor = float(self.rules.get('sell_factor', 0.9))
        self.commission_rate = float(self.rules.get('commission_rate', 0.001))
        self.target_profit = float(self.rules.get('target_profit', 0.002))

        # DCOM parameters
        self.working_capital_percent = float(self.rules.get('working_capital_percent', 0.60))
        self.ema_anchor_period = int(self.rules.get('ema_anchor_period', 200))
        self.aggressive_spacing = float(self.rules.get('aggressive_spacing_percent', 0.02))
        self.conservative_spacing = float(self.rules.get('conservative_spacing_percent', 0.04))
        self.initial_order_size_usd = float(self.rules.get('initial_order_size_usd', 5.00))
        self.order_progression_factor = float(self.rules.get('order_progression_factor', 1.20))

    def evaluate_buy_signal(self, market_data: dict, open_positions: list, last_buy_price: float | None) -> tuple[bool, str, str]:
        """
        Evaluates if a buy signal is present based on DCOM logic.
        Returns a tuple of (should_buy, mode, reason).
        """
        current_price = market_data.get('close')
        ema_anchor_key = f'ema_{self.ema_anchor_period}'
        ema_anchor_value = market_data.get(ema_anchor_key)

        if current_price is None or ema_anchor_value is None:
            return False, "N/A", f"Missing critical data: price or {ema_anchor_key}"

        # 1. Determine Operating Mode
        if current_price > ema_anchor_value:
            mode = "Aggressive"
            spacing = self.aggressive_spacing
        else:
            mode = "Conservative"
            spacing = self.conservative_spacing

        # 2. Check Spacing Trigger
        # If there are no open positions, we are always ready for the first buy.
        if not open_positions:
            return True, mode, "Ready for initial position"

        # If there are open positions, check if the price fell enough since the last buy.
        if last_buy_price is None:
            # This case should ideally not happen if there are open positions, but as a safeguard:
            return False, mode, "Cannot determine spacing (last buy price unknown)"

        price_fell_enough = current_price <= last_buy_price * (1 - spacing)

        if price_fell_enough:
            reason = f"Price dropped >{spacing:.1%} since last buy"
            return True, mode, reason
        else:
            reason = f"Price has not dropped >{spacing:.1%}"
            return False, mode, reason

    def get_next_buy_amount(self, cash_balance: float, open_positions_value: float, num_open_positions: int) -> float:
        """
        Calculates the USDT amount for the next purchase based on DCOM rules.
        Returns 0 if the buy cannot be executed due to capital limits.
        """
        # 1. Equity and Capital Calculation
        total_equity = cash_balance + open_positions_value
        working_capital = total_equity * self.working_capital_percent
        remaining_buying_power = working_capital - open_positions_value

        # 2. Order Sizing
        # Progressively increase order size based on the number of open positions
        # Cap the number of positions for sizing to prevent astronomical order sizes
        num_positions_for_sizing = min(num_open_positions, 20)
        next_order_size = self.initial_order_size_usd * (self.order_progression_factor ** num_positions_for_sizing)

        # 3. Capital Management Check
        # Ensure the bot can't use more than its allocated Working Capital
        if next_order_size <= remaining_buying_power:
            return next_order_size
        else:
            # Not enough buying power for the next calculated order size
            return 0

    def calculate_sell_target_price(self, purchase_price: float) -> float:
        """
        Calculates the target sell price based on the purchase price, commission,
        and target profit.
        """
        # Formula to calculate the price needed to break even, accounting for commissions on both buy and sell
        # P_sell * (1 - commission) = P_buy * (1 + commission)
        # P_sell_breakeven = P_buy * (1 + commission) / (1 - commission)
        numerator = purchase_price * (1 + self.commission_rate)
        denominator = (1 - self.commission_rate)

        if denominator == 0:
            return float('inf') # Avoid division by zero, return infinity

        break_even_price = numerator / denominator

        # Apply the target profit to the break-even price
        sell_target_price = break_even_price * (1 + self.target_profit)

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
        # Net Sales Revenue per unit = sell_price * (1 - commission_rate)
        # Proportional Purchase Cost per unit = buy_price * (1 + commission_rate)
        
        net_revenue_per_unit = sell_price * (1 - self.commission_rate)
        net_cost_per_unit = buy_price * (1 + self.commission_rate)
        
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
