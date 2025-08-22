from decimal import Decimal, InvalidOperation
import sys
import os

# This is needed to allow the script to be run from the root directory
# and still import modules from the 'jules_bot' package.
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from jules_bot.database.postgres_manager import PostgresManager
from jules_bot.utils.config_manager import config_manager
from jules_bot.utils.logger import logger

def get_summary():
    """
    Connects to the database, fetches all sell trades, and calculates a
    summary of performance including PnL in USD, PnL in BTC, and
    total assets sent to treasury.

    Returns:
        dict: A dictionary containing the performance summary.
    """
    logger.info("PerformanceService: Calculating performance summary...")
    total_usd_pnl = Decimal('0')
    total_btc_pnl = Decimal('0')
    total_treasury_btc = Decimal('0')
    sell_trade_count = 0

    try:
        db_config = config_manager.get_db_config('POSTGRES')
        db_manager = PostgresManager(config=db_config)

        # Fetch all trades from all environments
        all_trades = db_manager.get_all_trades_in_range(mode='trade')
        all_trades.extend(db_manager.get_all_trades_in_range(mode='test'))
        all_trades.extend(db_manager.get_all_trades_in_range(mode='backtest'))

        if not all_trades:
            logger.warning("PerformanceService: No trades found in the database.")
            return {}

        for trade in all_trades:
            if trade.order_type == 'sell':
                sell_trade_count += 1

                if trade.realized_pnl_usd is not None:
                    try:
                        total_usd_pnl += Decimal(trade.realized_pnl_usd)
                    except InvalidOperation:
                        pass # Logged in the calling script if needed

                pnl_usd = trade.realized_pnl_usd
                sell_price = trade.price
                if pnl_usd is not None and sell_price is not None and sell_price > Decimal('0'):
                    try:
                        pnl_btc = Decimal(pnl_usd) / Decimal(sell_price)
                        total_btc_pnl += pnl_btc
                    except InvalidOperation:
                        pass

                if trade.hodl_asset_amount is not None:
                    try:
                        total_treasury_btc += Decimal(trade.hodl_asset_amount)
                    except InvalidOperation:
                        pass

        summary = {
            "sell_trade_count": sell_trade_count,
            "total_usd_pnl": f"{total_usd_pnl:,.4f}",
            "total_btc_pnl": f"{total_btc_pnl:.8f}",
            "total_treasury_btc": f"{total_treasury_btc:.8f}"
        }
        logger.info(f"PerformanceService: Summary calculated successfully: {summary}")
        return summary

    except Exception as e:
        logger.error(f"PerformanceService: An error occurred during calculation: {e}", exc_info=True)
        return {"error": str(e)}
