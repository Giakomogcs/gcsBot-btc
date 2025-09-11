import sys
import os
import typer
from collections import defaultdict
from decimal import Decimal, getcontext

# Add project root to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from jules_bot.utils.config_manager import config_manager
from jules_bot.database.postgres_manager import PostgresManager
from jules_bot.utils.logger import logger

# Set precision for Decimal calculations
getcontext().prec = 16

def main(bot_name: str = typer.Argument(..., help="The name of the bot to validate data for.")):
    """
    Analyzes the entire trade history for a bot to check for data integrity.
    Checks for:
    1. Orphan Sells: Sell trades that are not linked to any buy trade.
    2. Quantity Mismatches: Buy trades where the linked sell quantities do not add up correctly.
    3. Status Inconsistencies: Buy trades marked 'OPEN' that should be 'CLOSED', and vice-versa.
    """
    logger.info(f"Starting data validation for bot: {bot_name}")

    try:
        # This script is run manually with a bot_name argument, so the config_manager
        # singleton may have initialized with the wrong context. We must manually
        # update its state before proceeding.
        config_manager.bot_name = bot_name
        db_manager = PostgresManager()

        logger.info(f"Fetching all trades from the database for schema '{db_manager.bot_name}' (no date limit)...")
        # Because we changed the default start_date to None, this gets all trades
        all_trades = db_manager.get_all_trades_in_range()
        logger.info(f"Found a total of {len(all_trades)} trades.")

        buy_trades = {t.trade_id: t for t in all_trades if t.order_type == 'buy'}
        sell_trades = [t for t in all_trades if t.order_type == 'sell']
        
        # --- Validation Logic ---
        
        sells_per_buy = defaultdict(list)
        orphan_sells = []
        
        for sell in sell_trades:
            if sell.linked_trade_id and sell.linked_trade_id in buy_trades:
                sells_per_buy[sell.linked_trade_id].append(sell)
            else:
                orphan_sells.append(sell)

        # --- Analysis ---
        quantity_mismatches = []
        status_inconsistencies = []

        for buy_id, buy_trade in buy_trades.items():
            linked_sells = sells_per_buy.get(buy_id, [])
            total_sell_qty = sum(Decimal(str(s.quantity)) for s in linked_sells)
            buy_qty = Decimal(str(buy_trade.quantity))
            
            # Check 1: Quantity and Status Mismatch for CLOSED trades
            if buy_trade.status == 'CLOSED':
                if total_sell_qty != buy_qty:
                    quantity_mismatches.append({
                        "buy_id": buy_id,
                        "buy_qty": buy_qty,
                        "total_sell_qty": total_sell_qty,
                        "status": "CLOSED",
                        "reason": "Sum of sells does not equal buy quantity."
                    })
            
            # Check 2: Quantity and Status Mismatch for OPEN trades
            elif buy_trade.status == 'OPEN':
                if total_sell_qty >= buy_qty:
                    status_inconsistencies.append({
                        "buy_id": buy_id,
                        "buy_qty": buy_qty,
                        "total_sell_qty": total_sell_qty,
                        "status": "OPEN",
                        "reason": "Trade is OPEN, but sell quantity is >= buy quantity. Should be CLOSED."
                    })
            
            # Check 3: Buy is closed but has no sells linked
            elif buy_trade.status == 'CLOSED' and not linked_sells:
                 status_inconsistencies.append({
                        "buy_id": buy_id,
                        "buy_qty": buy_qty,
                        "total_sell_qty": total_sell_qty,
                        "status": "CLOSED",
                        "reason": "Trade is CLOSED, but has no sell trades linked to it."
                    })


        # --- Reporting ---
        print("\n--- Data Validation Report ---")
        print("=" * 30)
        
        print(f"\nAnalyzed {len(all_trades)} trades for bot '{bot_name}':")
        print(f"  - {len(buy_trades)} Buy Trades")
        print(f"  - {len(sell_trades)} Sell Trades")

        # Report on Orphan Sells
        print("\n--- 1. Orphan Sell Check ---")
        if not orphan_sells:
            print("✅ SUCCESS: No orphan sell trades found.")
        else:
            print(f"❌ CRITICAL: Found {len(orphan_sells)} sell trades not linked to any known buy trade!")
            for sell in orphan_sells:
                print(f"  - Sell ID: {sell.trade_id}, Binance ID: {sell.binance_trade_id}, Qty: {sell.quantity}")

        # Report on Quantity Mismatches
        print("\n--- 2. Quantity Mismatch Check ---")
        if not quantity_mismatches:
            print("✅ SUCCESS: No quantity mismatches found for CLOSED trades.")
        else:
            print(f"❌ WARNING: Found {len(quantity_mismatches)} CLOSED buy trades with inconsistent sell quantities.")
            for mismatch in quantity_mismatches:
                print(f"  - Buy ID: {mismatch['buy_id']}, Buy Qty: {mismatch['buy_qty']}, Sum of Sells: {mismatch['total_sell_qty']}")

        # Report on Status Inconsistencies
        print("\n--- 3. Status Inconsistency Check ---")
        if not status_inconsistencies:
            print("✅ SUCCESS: No status inconsistencies found.")
        else:
            print(f"❌ WARNING: Found {len(status_inconsistencies)} trades with status inconsistencies.")
            for issue in status_inconsistencies:
                print(f"  - Buy ID: {issue['buy_id']}, Status: {issue['status']}, Reason: {issue['reason']}")

        print("\n" + "=" * 30)
        print("Report finished.\n")

    except Exception as e:
        logger.error(f"An error occurred during data validation: {e}", exc_info=True)
        raise typer.Exit(1)

if __name__ == "__main__":
    typer.run(main)
