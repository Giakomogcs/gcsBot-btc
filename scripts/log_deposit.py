import os
import sys
import typer
from jules_bot.database.models import Deposit

# Add project root to sys.path to allow imports from other directories
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from jules_bot.utils.config_manager import ConfigManager
from jules_bot.database.postgres_manager import PostgresManager
from jules_bot.utils.logger import logger

def main(
    amount: float = typer.Argument(..., help="The amount of USD deposited."),
    notes: str = typer.Option(None, "--notes", "-n", help="Optional notes for the deposit."),
):
    """
    Logs a new deposit to the database.
    """
    logger.info(f"Logging a new deposit of ${amount:.2f}")

    try:
        config_manager = ConfigManager()
        db_config = config_manager.get_db_config('POSTGRES')
        db_manager = PostgresManager(config=db_config)

        deposit = Deposit(
            amount_usd=amount,
            notes=notes
        )

        db_manager.log_deposit(deposit)

        logger.info("Successfully logged deposit.")

    except Exception as e:
        logger.error(f"A critical error occurred while logging deposit: {e}", exc_info=True)
        raise typer.Exit(code=1)

if __name__ == "__main__":
    typer.run(main)
