import os
import sys
import typer
import uuid
from decimal import Decimal
from typing_extensions import Annotated

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from jules_bot.core_logic.trader import Trader
from jules_bot.utils.config_manager import config_manager
from jules_bot.utils.logger import logger
from jules_bot.database.postgres_manager import PostgresManager
from jules_bot.core.schemas import TradePoint

def main(
    trade_id: Annotated[str, typer.Argument(
        help="The unique ID of the trade to sell.",
        show_default=False
    )],
    percentage: Annotated[float, typer.Argument(
        help="The percentage of the position to sell (e.g., 100 for 100%).",
        min=1.0,
        max=100.0,
        show_default=False
    )],
):
    """
    Directly executes a manual sell order for a percentage of an open position.
    """
    bot_name = os.getenv("BOT_NAME")
    if not bot_name:
        logger.error("CRITICAL ERROR: BOT_NAME environment variable is not set.")
        print("❌ CRITICAL ERROR: BOT_NAME environment variable is not set.")
        raise typer.Exit(code=1)

    mode = os.getenv("BOT_MODE", "test")
    logger.info(f"Initializing force_sell script for bot '{bot_name}' in '{mode}' mode.")
    logger.info(f"Received arguments: trade_id='{trade_id}', percentage='{percentage}%'")

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

    logger.info(f"Attempting manual sell of {percentage}% for trade_id {trade_id}.")

    try:
        # 1. Fetch the original buy trade from the database
        original_trade = db_manager.get_trade_by_trade_id(trade_id)
        if not original_trade:
            logger.error(f"Could not find an open trade with ID '{trade_id}'.")
            print(f"❌ Error: No open trade found with ID '{trade_id}'.")
            raise typer.Exit(code=1)
        
        logger.info(f"Found original trade: {original_trade.trade_id}, Status: {original_trade.status}, Quantity: {original_trade.quantity}")

        if original_trade.status != "OPEN":
            logger.warning(f"Trade {trade_id} is not OPEN. Current status: {original_trade.status}.")
            print(f"⚠️ Warning: Trade {trade_id} is not OPEN (Status: {original_trade.status}). Cannot sell.")
            raise typer.Exit()

        # 2. Prepare data for the sell order
        quantity_to_sell = (Decimal(str(original_trade.quantity)) * Decimal(str(percentage))) / Decimal('100')
        logger.info(f"Calculated quantity to sell: {quantity_to_sell} (Percentage: {percentage}%)")
        
        # This dict mimics the data structure the main bot loop would prepare
        position_data = {
            "trade_id": original_trade.trade_id,
            "quantity": quantity_to_sell,
            # Other fields like realized_pnl will be calculated after the sell
        }

        # 3. Execute the sell order
        run_id = f"manual_tui_{uuid.uuid4()}"
        decision_context = {"source": "tui_force_sell", "original_trade_id": trade_id, "sell_percentage": percentage}

        logger.info(f"Executing sell via trader for trade_id: {trade_id}, run_id: {run_id}")
        success, sell_result = trader.execute_sell(
            position_data=position_data,
            run_id=run_id,
            decision_context=decision_context
        )

        if success and sell_result:
            logger.info(f"Trader executed sell successfully. Result: {sell_result}")
            # 4. The trade was successful, now update the database
            
            # Calculate PnL
            entry_price = Decimal(str(original_trade.price))
            sell_price = Decimal(str(sell_result.get('price', 0)))
            quantity_sold = Decimal(str(sell_result.get('quantity', 0)))
            realized_pnl = (sell_price - entry_price) * quantity_sold
            logger.info(f"Calculated PnL: ${realized_pnl:.2f} (Entry: ${entry_price}, Exit: ${sell_price}, Qty: {quantity_sold})")
            
            # Create the sell trade record
            sell_trade_data = sell_result.copy()
            sell_trade_data.update({
                'order_type': 'sell',
                'status': 'CLOSED',
                'run_id': run_id,
                'strategy_name': trader.strategy_name,
                'exchange': 'binance',
                'realized_pnl_usd': realized_pnl,
                'price': sell_price, # Ensure price is Decimal
                'quantity': quantity_sold, # Ensure quantity is Decimal
                'decision_context': decision_context,
            })
            
            sell_trade_point = TradePoint(**sell_trade_data)
            db_manager.log_trade(sell_trade_point)
            logger.info(f"Logged sell trade record to database. Sell Trade ID: {sell_trade_point.trade_id}")
            
            # Mark the original buy trade as CLOSED
            # Note: This assumes a 100% sell. Partial sells would require updating quantity.
            # For this implementation, we'll assume 100% as per the UI button's typical function.
            if percentage == 100:
                db_manager.update_trade_status(trade_id, "CLOSED")
                logger.info(f"Updated original trade {trade_id} status to CLOSED.")
            else:
                # Handle partial sell logic if necessary in the future
                # For now, just log a warning.
                logger.warning(f"Partial sell ({percentage}%) executed. The original buy trade {trade_id} is still marked OPEN.")
                print(f"⚠️ Partial sell executed. Original trade {trade_id} remains OPEN.")


            print(f"✅ Successfully executed sell of {quantity_sold} of {sell_result.get('symbol')}.")
            print(f"   Original Trade ID: {trade_id}")
            print(f"   Realized PnL: ${realized_pnl:.2f}")
        else:
            logger.error(f"Failed to execute sell order. Result: {sell_result}")
            print("❌ Failed to execute sell order. Check logs for details.")
            raise typer.Exit(code=1)

    except Exception as e:
        logger.error(f"An unexpected error occurred during sell execution: {e}", exc_info=True)
        print(f"❌ An unexpected error occurred: {e}")
        raise typer.Exit(code=1)

if __name__ == "__main__":
    typer.run(main)