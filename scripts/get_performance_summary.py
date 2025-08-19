import sys
import os

# Add the project root to the Python path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, project_root)

from jules_bot.services.performance_service import get_summary
from jules_bot.utils.logger import logger

def main():
    """
    Main function to get and display the performance summary.
    """
    logger.info("Running performance summary script...")
    summary = get_summary()

    if not summary or "error" in summary:
        print("\n❌ Could not retrieve performance summary.")
        if "error" in summary:
            print(f"   Error: {summary['error']}")
        return

    print("\n" + "="*60)
    print("💰 Bot Performance Summary (Calculated from All Sell Trades) 💰")
    print("="*60)
    print(f"Data calculated from a total of {summary.get('sell_trade_count', 0)} sell transactions.")
    print("-" * 60)
    print(f"1. Total Realized Profit (USD):  $ {summary.get('total_usd_pnl', '0.00')}")
    print(f"2. Total Realized Profit (BTC):    {summary.get('total_btc_pnl', '0.00000000')} BTC")
    print(f"3. Total BTC Sent to Treasury:     {summary.get('total_treasury_btc', '0.00000000')} BTC")
    print("="*60)

if __name__ == "__main__":
    main()
