import os
import sys
import typer
import uuid
from decimal import Decimal
from typing import Optional
from typing_extensions import Annotated

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from jules_bot.core_logic.trader import Trader
from jules_bot.utils.config_manager import config_manager
from jules_bot.utils.logger import logger
from jules_bot.database.postgres_manager import PostgresManager
from jules_bot.core.schemas import TradePoint

def main(
    usd_amount: Annotated[float, typer.Argument(
        help="The amount in USD to buy.",
        min=1.0,
        show_default=False
    )],
    # --- Dummy arguments to absorb extra parameters passed by the TUI ---
    # These are not used in the script but prevent Typer from crashing.
    container_id: Annotated[Optional[str], typer.Option(help="Dummy")] = None,
    mode_dummy: Annotated[Optional[str], typer.Option("--mode", help="Dummy")] = None,
    bot_name_dummy: Annotated[Optional[str], typer.Option("--bot-name", help="Dummy")] = None,
):
    """
    Directly executes a manual buy order for a specific USD amount.
    """
    bot_name = os.getenv("BOT_NAME")
    if not bot_name:
        logger.error("CRITICAL ERROR: BOT_NAME environment variable is not set.")
        print("❌ CRITICAL ERROR: BOT_NAME environment variable is not set.")
        raise typer.Exit(code=1)

    mode = os.getenv("BOT_MODE", "test")
    logger.info(f"Initializing force_buy script for bot '{bot_name}' in '{mode}' mode.")
    logger.info(f"Received arguments: usd_amount='{usd_amount}'")

    try:
        config_manager.initialize(bot_name)
        db_manager = PostgresManager()
        trader = Trader(mode=mode)
    except Exception as e:
        logger.error(f"Failed to initialize components: {e}", exc_info=True)
        print(f"❌ Error during initialization: {e}")
        raise typer.Exit(code=1)

    if not trader.is_ready:
        logger.error("Trader is not ready. Check API keys and connection.")
        print("❌ Trader is not ready. Check API keys and connection.")
        raise typer.Exit(code=1)

    logger.info(f"Attempting manual buy of ${usd_amount}.")

    try:
        # 1. Execute the buy order
        run_id = f"manual_tui_{uuid.uuid4()}"
        decision_context = {"source": "tui_force_buy", "usd_amount": usd_amount}

        logger.info(f"Executing buy via trader for usd_amount: {usd_amount}, run_id: {run_id}")
        success, buy_result = trader.execute_buy(
            amount_usdt=float(usd_amount),
            run_id=run_id,
            decision_context=decision_context
        )

        if success and buy_result:
            logger.info(f"Trader executed buy successfully. Result: {buy_result}")
            # 2. The trade was successful, now log it to the database
            
            # The trader returns a dict with all necessary fields.
            # We just need to ensure the types are correct for the DB schema.
            buy_trade_data = buy_result.copy()
            buy_trade_data.update({
                'order_type': 'buy',
                'status': 'OPEN',
                'price': Decimal(str(buy_result.get('price'))),
                'quantity': Decimal(str(buy_result.get('quantity'))),
                'usd_value': Decimal(str(buy_result.get('usd_value'))),
                'strategy_name': trader.strategy_name,
                'exchange': 'binance'
            })

            # Remove any fields from the result that are not in the TradePoint schema
            # to prevent the TypeError. The trader result might contain extra info.
            all_known_fields = {f.name for f in TradePoint.__dataclass_fields__.values()}
            filtered_trade_data = {k: v for k, v in buy_trade_data.items() if k in all_known_fields}

            buy_trade_point = TradePoint(**filtered_trade_data)
            db_manager.log_trade(buy_trade_point)
            logger.info(f"Successfully logged manual buy to database. Trade ID: {buy_result.get('trade_id')}")

            # --- Signal the main bot to refresh ---
            try:
                signal_dir = "/app/.tui_files"
                os.makedirs(signal_dir, exist_ok=True)
                signal_file_path = os.path.join(signal_dir, f".force_refresh_{bot_name}")
                with open(signal_file_path, "w") as f:
                    pass  # Create an empty file
                logger.info(f"Created signal file at {signal_file_path} to trigger TUI refresh.")
            except Exception as e:
                # Log an error but don't fail the entire script, as the trade itself was successful.
                logger.error(f"Could not create signal file for TUI refresh: {e}", exc_info=True)

            print(f"✅ Successfully executed buy of {buy_result.get('quantity')} of {buy_result.get('symbol')} for ${buy_result.get('usd_value'):.2f}.")
            print(f"   Trade ID: {buy_result.get('trade_id')}")
        else:
            logger.error(f"Failed to execute buy order. Result: {buy_result}")
            print("❌ Failed to execute buy order. Check logs for details.")
            raise typer.Exit(code=1)

    except Exception as e:
        logger.error(f"An unexpected error occurred during buy execution: {e}", exc_info=True)
        print(f"❌ An unexpected error occurred: {e}")
        raise typer.Exit(code=1)

if __name__ == "__main__":
    typer.run(main)
