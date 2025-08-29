import sys
import os
import typer
from collections import defaultdict

# Add project root to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from jules_bot.utils.config_manager import config_manager
from jules_bot.database.postgres_manager import PostgresManager
from jules_bot.utils.logger import logger

def main(bot_name: str = typer.Argument(..., help="The name of the bot to validate data for.")):
    """
    Analyzes the trade history for a given bot to check for data integrity issues,
    specifically looking for single 'buy' trades that have multiple 'sell' trades linked to them.
    """
    logger.info(f"Starting data validation for bot: {bot_name}")

    try:
        config_manager.initialize(bot_name)
        db_manager = PostgresManager()

        logger.info("Fetching all trades from the database...")
        all_trades = db_manager.get_all_trades_in_range()
        logger.info(f"Found a total of {len(all_trades)} trades.")

        buy_trades = [t for t in all_trades if t.order_type == 'buy']
        sell_trades = [t for t in all_trades if t.order_type == 'sell']
        
        logger.info(f"Total Buy Trades: {len(buy_trades)}")
        logger.info(f"Total Sell Trades: {len(sell_trades)}")

        # --- Validation Logic ---
        
        # Dictionary to store sell counts for each buy trade
        # Key: linked_trade_id (which is the original buy trade's id)
        # Value: list of sell trades
        sells_per_buy = defaultdict(list)
        
        sells_with_linked_id = 0
        for trade in sell_trades:
            if trade.linked_trade_id:
                sells_with_linked_id += 1
                sells_per_buy[trade.linked_trade_id].append(trade.trade_id)

        logger.info(f"Found {sells_with_linked_id} sell trades with a linked_trade_id.")

        # Find duplicates
        duplicate_sells = {buy_id: sell_ids for buy_id, sell_ids in sells_per_buy.items() if len(sell_ids) > 1}

        print("\n--- Data Validation Report ---")
        print("=" * 30)
        
        print(f"\nTotal Trades Analyzed: {len(all_trades)}")
        print(f"  - Buy Trades: {len(buy_trades)}")
        print(f"  - Sell Trades: {len(sell_trades)}")
        print(f"  - Sell Trades with Link to a Buy: {sells_with_linked_id}")

        if not duplicate_sells:
            print("\n✅ SUCCESS: No duplicate sells found for any single buy trade.")
        else:
            print(f"\n❌ CRITICAL: Found {len(duplicate_sells)} buy trades with multiple sells linked to them!")
            print("This confirms the suspicion of data corruption. Details below:")
            for buy_id, sell_ids in duplicate_sells.items():
                print(f"\n  - Buy Trade ID: {buy_id}")
                print(f"    - Linked Sell Trade IDs ({len(sell_ids)}): {', '.join(sell_ids)}")
        
        print("\n" + "=" * 30)
        print("Report finished.\n")

    except Exception as e:
        logger.error(f"An error occurred during data validation: {e}", exc_info=True)
        raise typer.Exit(1)

if __name__ == "__main__":
    typer.run(main)
