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
    bot_name = os.getenv("BOT_NAME")
    if not bot_name:
        logger.error("ERRO CRÍTICO: A variável de ambiente BOT_NAME não está definida.")
        sys.exit(1)

    logger.info(f"Received request to force buy ${amount_usd:.2f} for bot '{bot_name}'.")

    try:
        # Ensure the command directory for the specific bot exists
        bot_command_dir = os.path.join(COMMAND_DIR, bot_name)
        os.makedirs(bot_command_dir, exist_ok=True)

        # Define the command payload
        command = {
            "type": "force_buy",
            "amount_usd": amount_usd
        }

        # Create a unique filename for the command
        filename = f"cmd_buy_{int(time.time() * 1000)}.json"
        filepath = os.path.join(bot_command_dir, filename)

        # Write the command to the file
        with open(filepath, "w") as f:
            json.dump(command, f)

        logger.info(f"Successfully created command file: {filepath}")
        print(f"✅ Buy command for ${amount_usd:.2f} has been issued to bot '{bot_name}'.")
        print(f"   The bot should execute it shortly.")

    except IOError as e:
        logger.error(f"Failed to write command file: {e}", exc_info=True)
        print(f"❌ Error: Could not write command file to '{bot_command_dir}'.")
        raise typer.Exit(code=1)
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}", exc_info=True)
        print(f"❌ An unexpected error occurred.")
        raise typer.Exit(code=1)

if __name__ == "__main__":
    typer.run(main)