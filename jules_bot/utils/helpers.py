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

