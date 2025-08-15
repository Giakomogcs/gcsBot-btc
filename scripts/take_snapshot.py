import os
import sys
import typer

# Add project root to sys.path to allow imports from other directories
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from jules_bot.utils.config_manager import ConfigManager
from jules_bot.database.postgres_manager import PostgresManager
from jules_bot.services.status_service import StatusService
from jules_bot.research.live_feature_calculator import LiveFeatureCalculator
from jules_bot.database.models import PortfolioSnapshot
from jules_bot.utils.logger import logger

def main(
    mode: str = typer.Argument(
        "test",
        help="The environment to take a snapshot for ('trade' or 'test')."
    )
):
    """
    Takes a snapshot of the bot's portfolio and performance metrics and saves it to the database.
    """
    logger.info(f"Taking portfolio snapshot for '{mode}' environment...")

    try:
        config_manager = ConfigManager()
        db_config = config_manager.get_db_config('POSTGRES')
        db_manager = PostgresManager(config=db_config)
        feature_calculator = LiveFeatureCalculator(db_manager, mode=mode)
        status_service = StatusService(db_manager, config_manager, feature_calculator)

        bot_id = f"jules_{mode}_bot"

        status_data = status_service.get_extended_status(mode, bot_id)

        if "error" in status_data:
            logger.error(f"An error occurred while fetching data: {status_data['error']}")
            raise typer.Exit(code=1)

        # Create a snapshot object from the status data
        performance_data = status_data.get("portfolio_performance", {})

        # Get balances
        btc_balance = next((bal['free'] for bal in status_data.get("wallet_balances", []) if bal.get("asset") == "BTC"), 0)
        usdt_balance = next((bal['free'] for bal in status_data.get("wallet_balances", []) if bal.get("asset") == "USDT"), 0)

        snapshot = PortfolioSnapshot(
            bot_id=bot_id,
            mode=mode,
            total_portfolio_value_usd=status_data.get("total_wallet_usd_value"),
            btc_balance=btc_balance,
            usdt_balance=usdt_balance,
            cumulative_deposits_usd=performance_data.get("cumulative_deposits_usd"),
            cumulative_realized_pnl_usd=performance_data.get("cumulative_realized_pnl_usd"),
            net_portfolio_growth_usd=performance_data.get("net_portfolio_growth_usd"),
            open_positions_count=len(status_data.get("open_positions_status", [])),
            # avg_entry_price is not calculated yet, will add later
        )

        db_manager.log_portfolio_snapshot(snapshot)

        logger.info("Successfully took and saved portfolio snapshot.")

    except Exception as e:
        logger.error(f"A critical error occurred: {e}", exc_info=True)
        raise typer.Exit(code=1)

if __name__ == "__main__":
    typer.run(main)
