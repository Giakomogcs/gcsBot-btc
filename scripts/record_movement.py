import argparse
import sys
import os

# Add project root to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from jules_bot.utils.config_manager import config_manager
from jules_bot.database.portfolio_manager import PortfolioManager

def record_movement():
    """
    Command-line script to record a financial movement (deposit or withdrawal).
    """
    parser = argparse.ArgumentParser(description="Record a financial movement in the portfolio.")
    parser.add_argument(
        "movement_type",
        type=str,
        choices=["DEPOSIT", "WITHDRAWAL"],
        help="The type of movement."
    )
    parser.add_argument(
        "amount_usd",
        type=float,
        help="The amount in USD."
    )
    parser.add_argument(
        "--notes",
        type=str,
        default=None,
        help="Optional notes for the movement."
    )
    args = parser.parse_args()

    if args.amount_usd <= 0:
        print("Error: Amount must be a positive number.")
        sys.exit(1)

    try:
        # Initialize PortfolioManager
        db_config = config_manager.get_section('POSTGRES')
        portfolio_manager = PortfolioManager(db_config)

        result = portfolio_manager.create_financial_movement(
            movement_type=args.movement_type.upper(),
            amount_usd=args.amount_usd,
            notes=args.notes
        )

        if result:
            print(f"Successfully recorded {result.movement_type} of ${result.amount_usd:.2f}")
        else:
            print("Failed to record financial movement. Check logs for details.")
            sys.exit(1)

    except Exception as e:
        print(f"An error occurred: {e}")
        sys.exit(1)

if __name__ == "__main__":
    record_movement()
