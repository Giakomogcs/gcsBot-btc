import json
import os
import sys
import time
import typer
from typing_extensions import Annotated

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from jules_bot.utils.logger import logger

COMMAND_DIR = "commands"

def main(
    trade_id: Annotated[str, typer.Argument(
        help="The unique ID of the trade to sell.",
        show_default=False
    )],
    percentage: Annotated[float, typer.Argument(
        help="The percentage of the position to sell (e.g., 90 for 90%).",
        min=1.0,
        max=100.0,
        show_default=False
    )]
):
    """
    Creates a command file to instruct a running bot to force sell a position.
    """
    logger.info(f"Received request to force sell {percentage}% of trade {trade_id}.")

    try:
        # Ensure the command directory exists
        os.makedirs(COMMAND_DIR, exist_ok=True)

        # Define the command payload
        command = {
            "type": "force_sell",
            "trade_id": trade_id,
            "percentage": percentage
        }

        # Create a unique filename for the command
        filename = f"cmd_sell_{int(time.time() * 1000)}.json"
        filepath = os.path.join(COMMAND_DIR, filename)

        # Write the command to the file
        with open(filepath, "w") as f:
            json.dump(command, f)

        logger.info(f"Successfully created command file: {filepath}")
        print(f"✅ Sell command for {percentage}% of trade {trade_id} has been issued.")
        print(f"   A running bot should execute it shortly.")

    except IOError as e:
        logger.error(f"Failed to write command file: {e}", exc_info=True)
        print(f"❌ Error: Could not write command file to '{COMMAND_DIR}'.")
        raise typer.Exit(code=1)
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}", exc_info=True)
        print(f"❌ An unexpected error occurred.")
        raise typer.Exit(code=1)

if __name__ == "__main__":
    typer.run(main)
