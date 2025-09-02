import os
import sys
import typer
import uuid
import json
from typing_extensions import Annotated

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from jules_bot.utils.logger import logger

def main(
    usd_amount: Annotated[float, typer.Argument(
        help="The amount in USD to buy.",
        min=1.0,
        show_default=False
    )],
):
    """
    Creates a command file to instruct the running bot to execute a manual buy.
    """
    bot_name = os.getenv("BOT_NAME")
    if not bot_name:
        logger.error("CRITICAL ERROR: BOT_NAME environment variable is not set.")
        print("❌ CRITICAL ERROR: BOT_NAME environment variable is not set.")
        raise typer.Exit(code=1)

    command_dir = os.path.join("/app", "commands", bot_name)

    try:
        os.makedirs(command_dir, exist_ok=True)
        logger.info(f"Command directory '{command_dir}' is ready.")
    except OSError as e:
        logger.error(f"Failed to create command directory '{command_dir}': {e}", exc_info=True)
        print(f"❌ Failed to create command directory: {e}")
        raise typer.Exit(code=1)

    command = {
        "type": "force_buy",
        "amount_usd": str(usd_amount) # Keep as string for consistency
    }

    command_filename = f"force_buy_{uuid.uuid4()}.json"
    command_filepath = os.path.join(command_dir, command_filename)

    try:
        with open(command_filepath, "w") as f:
            json.dump(command, f)

        logger.info(f"Successfully created buy command file at {command_filepath}")
        print(f"✅ Successfully created buy command for ${usd_amount:.2f}.")
        print(f"   The bot will execute it on its next cycle.")

    except Exception as e:
        logger.error(f"Failed to write command file to {command_filepath}: {e}", exc_info=True)
        print(f"❌ Failed to write command file: {e}")
        raise typer.Exit(code=1)

if __name__ == "__main__":
    typer.run(main)
