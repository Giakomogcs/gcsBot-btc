from typing import Dict

def check_for_legacy_hold(position: Dict, current_price: float, legacy_trigger_percent: float) -> bool:
    """
    Determines if a position should be marked as Legacy Hold.
    Returns True if the condition is met, False otherwise.

    Args:
        position (Dict): The position object, as a dictionary or pandas Series.
        current_price (float): The current market price of the asset.
        legacy_trigger_percent (float): The PnL percentage threshold to trigger legacy hold.
    """
    # .get() is safer than direct access; avoids KeyErrors if the field is missing.
    is_already_legacy = position.get('is_legacy_hold', False)

    # Calculate unrealized PnL percentage
    entry_price = position.get('entry_price', 0.0)
    if entry_price == 0.0:
        return False # Avoid division by zero

    pnl_percent = (current_price - entry_price) / entry_price * 100

    if not is_already_legacy and pnl_percent <= legacy_trigger_percent:
        return True
    return False
