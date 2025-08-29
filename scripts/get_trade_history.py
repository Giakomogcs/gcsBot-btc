import json
import sys
import os
import typer
from typing import Optional

# Add project root to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from jules_bot.utils.config_manager import config_manager
from jules_bot.database.postgres_manager import PostgresManager

def main(
    bot_name: str = typer.Argument(..., help="The name of the bot to get history for."),
    start_date: Optional[str] = typer.Option(None, "--start-date", help="Start date in YYYY-MM-DD format."),
    end_date: Optional[str] = typer.Option(None, "--end-date", help="End date in YYYY-MM-DD format.")
):
    """
    Fetches the trade history for a given bot and prints it as JSON.
    Supports filtering by date range.
    """
    if not bot_name:
        print(json.dumps({"error": "Bot name not provided."}), file=sys.stderr)
        raise typer.Exit(1)

    try:
        config_manager.initialize(bot_name)
        db_manager = PostgresManager()

        # Use the provided date filters, or None if not provided.
        # The db_manager handles None as "no filter".
        all_trades = db_manager.get_all_trades_in_range(
            start_date=start_date,
            end_date=end_date
        )

        history_list = [trade.to_dict() for trade in all_trades]
        print(json.dumps(history_list, indent=4, default=str))

    except Exception as e:
        print(json.dumps({"error": f"Failed to get trade history: {e}"}), file=sys.stderr)
        raise typer.Exit(1)

if __name__ == "__main__":
    typer.run(main)
