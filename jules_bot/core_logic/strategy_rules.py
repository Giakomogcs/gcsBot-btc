from jules_bot.utils.config_manager import ConfigManager
from jules_bot.utils.logger import logger

class StrategyRules:
    """
    Implements the Dynamic Capital & Opportunity Management (DCOM) strategy rules.
    This class is responsible for calculating order sizes and evaluating
    market conditions based on the DCOM framework, but it does not make the
    final buy/sell decision.
    """
    def __init__(self, config_manager: ConfigManager):
        self.rules = config_manager.get_section('STRATEGY_RULES')
        
        # --- Sell & Profit Logic ---
        self.commission_rate = float(self.rules.get('commission_rate', 0.001))
        self.sell_factor = float(self.rules.get('sell_factor', 0.9))
        self.target_profit = float(self.rules.get('target_profit', 0.002))

        # --- DCOM Configuration ---
        self.working_capital_percent = float(self.rules.get('working_capital_percent', 0.60))
        self.ema_anchor_period = int(self.rules.get('ema_anchor_period', 200))
        self.aggressive_spacing_percent = float(self.rules.get('aggressive_spacing_percent', 0.02))
        self.conservative_spacing_percent = float(self.rules.get('conservative_spacing_percent', 0.04))
        
        # --- Order Sizing Logic ---
        self.initial_order_size_usd = float(self.rules.get('initial_order_size_usd', 5.00))
        self.order_progression_factor = float(self.rules.get('order_progression_factor', 1.20))

    def get_operating_mode(self, current_price: float, ema_anchor: float) -> tuple[str, float]:
        """
        Determines the current operating mode (Aggressive/Conservative) and the
        corresponding spacing percentage based on the anchor EMA.

        Returns:
            A tuple containing the mode ('AGGRESSIVE' or 'CONSERVATIVE') and the
            spacing percentage for that mode.
        """
        if current_price > ema_anchor:
            return "AGGRESSIVE", self.aggressive_spacing_percent
        else:
            return "CONSERVATIVE", self.conservative_spacing_percent

    def should_place_new_order(self, current_price: float, last_buy_price: float | None, required_spacing: float) -> bool:
        """
        Checks if the price has dropped enough since the last buy to justify a new order.
        """
        if last_buy_price is None:
            # This is the first purchase, so it's always allowed.
            return True
        
        price_fall_percent = (last_buy_price - current_price) / last_buy_price
        
        if price_fall_percent >= required_spacing:
            logger.info(f"Price fell {price_fall_percent:.2%} since last buy (required: {required_spacing:.2%}). Triggering new buy evaluation.")
            return True
            
        return False

    def calculate_next_order_size(self, open_positions_count: int) -> float:
        """
        Calculates the size of the next buy order in USD, using progressive sizing.
        The first order is the initial size, and each subsequent order is
        increased by the progression factor.

        Args:
            open_positions_count (int): The number of currently open positions.

        Returns:
            The calculated size for the next order in USD.
        """
        if open_positions_count == 0:
            return self.initial_order_size_usd
        else:
            # The formula is: initial_size * (factor ^ n)
            # where n is the number of existing positions.
            return self.initial_order_size_usd * (self.order_progression_factor ** open_positions_count)

    def calculate_sell_target_price(self, purchase_price: float) -> float:
        """
        Calculates the target sell price based on the purchase price, commission,
        and target profit. (Unchanged from original logic).
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
        (Unchanged from original logic).
        """
        net_revenue_per_unit = sell_price * (1 - self.commission_rate)
        net_cost_per_unit = buy_price * (1 + self.commission_rate)
        profit_per_unit = net_revenue_per_unit - net_cost_per_unit
        realized_pnl = profit_per_unit * quantity_sold
        return realized_pnl

    def calculate_net_unrealized_pnl(self, entry_price: float, current_price: float, total_quantity: float) -> float:
        """
        Calculates the net unrealized PnL for an open position, factoring in
        the partial sale rule (90%) and commissions. (Unchanged from original logic).
        """
        quantity_to_sell = total_quantity * self.sell_factor
        net_unrealized_pnl = self.calculate_realized_pnl(
            buy_price=entry_price,
            sell_price=current_price,
            quantity_sold=quantity_to_sell
        )
        return net_unrealized_pnl
