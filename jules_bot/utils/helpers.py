def _calculate_progress_pct(current_price, start_price, target_price):
    """
    Calculates the percentage progress of a current value towards a target,
    relative to a starting point. Can exceed 100%.
    """
    if target_price is None or start_price is None or current_price is None:
        return 0.0
    # Avoid division by zero if start and target are the same
    if target_price == start_price:
        return 100.0 if current_price >= target_price else 0.0

    # Calculate the progress percentage
    progress = (current_price - start_price) / (target_price - start_price) * 100

    # Return the progress, but not less than 0
    return max(0, progress)
