import json
import os
import sys
import time
import typer

# Add project root to sys.path to allow imports if needed, and for consistency
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from jules_bot.utils.logger import logger

COMMAND_DIR = "commands"

def main(
    amount_usd: float = typer.Argument(
        ...,
        help="The amount in USD to buy.",
        min=0.0,
        show_default=False
    )
):
    """
    Creates a command file to instruct a running bot to execute a manual buy.
    """
    logger.info(f"Received request to force buy ${amount_usd:.2f}.")

    try:
        # Ensure the command directory exists
        os.makedirs(COMMAND_DIR, exist_ok=True)

        # Define the command payload
        command = {
            "type": "force_buy",
            "amount_usd": amount_usd
        }

        # Create a unique filename for the command
        filename = f"cmd_buy_{int(time.time() * 1000)}.json"
        filepath = os.path.join(COMMAND_DIR, filename)

        # Write the command to the file
        with open(filepath, "w") as f:
            json.dump(command, f)

        logger.info(f"Successfully created command file: {filepath}")
        print(f"✅ Buy command for ${amount_usd:.2f} has been issued.")
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
