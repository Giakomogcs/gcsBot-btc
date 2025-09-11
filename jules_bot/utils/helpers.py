from decimal import Decimal, InvalidOperation

def _calculate_progress_pct(current_price: Decimal, start_price: Decimal, target_price: Decimal) -> Decimal:
    """
    Calculates the percentage progress of a value from a starting point to a target.
    Clamps the result between 0 and 100.
    """
    if current_price is None or start_price is None or target_price is None:
        return Decimal('0.0')

    # Avoid division by zero if start and target prices are the same.
    if target_price == start_price:
        return Decimal('100.0') if current_price >= target_price else Decimal('0.0')

    try:
        # Calculate progress as a percentage. This works for both long and short scenarios.
        progress = (current_price - start_price) / (target_price - start_price) * Decimal('100')

        # Clamp the result between 0% and 100%.
        return max(Decimal('0'), min(progress, Decimal('100')))
    except (InvalidOperation, ZeroDivisionError):
        return Decimal('0.0')

def calculate_buy_progress(market_data: dict, current_params: dict, difficulty_factor: Decimal) -> tuple[Decimal, Decimal]:
    """
    Calculates the target price for the next buy and the progress towards it,
    considering the correct market regime (uptrend vs. downtrend).
    """
    try:
        current_price = Decimal(str(market_data.get('close')))
        high_price = Decimal(str(market_data.get('high', current_price)))
        ema_100 = market_data.get('ema_100')
        bbl = market_data.get('bbl_20_2_0')

        # If essential data is missing, can't determine target
        if any(v is None for v in [current_price, high_price, ema_100, bbl]):
            return Decimal('0'), Decimal('0')

        ema_100 = Decimal(str(ema_100))
        bbl = Decimal(str(bbl))

        # Determine which target is active based on market trend (mirroring strategy_rules.py)
        if current_price > ema_100:
            # UPTREND LOGIC: Target is based on a dip from the high price.
            base_buy_dip = current_params.get('buy_dip_percentage', Decimal('0.02'))
            adjusted_buy_dip_percentage = base_buy_dip + difficulty_factor
            target_price = high_price * (Decimal('1') - adjusted_buy_dip_percentage)
            # The "start price" for measuring progress is the recent high.
            start_price = high_price
        else:
            # DOWNTREND LOGIC: Target is the adjusted lower Bollinger Band.
            difficulty_multiplier = Decimal('1') - difficulty_factor
            target_price = bbl * difficulty_multiplier
            # The "start price" for measuring progress is the recent high.
            # When the current price drops from the high to the target, progress goes from 0 to 100.
            start_price = high_price

        progress = _calculate_progress_pct(current_price, start_price, target_price)

        return target_price, progress

    except (InvalidOperation, TypeError):
        return Decimal('0'), Decimal('0')
