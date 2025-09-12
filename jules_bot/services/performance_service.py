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

def get_summary(bot_name: str = None):
    """
    Connects to the database, fetches all sell trades for a specific bot,
    and calculates a summary of performance including PnL in USD, PnL in BTC,
    and total assets sent to treasury. The connection is scoped to the bot's
    schema via the config_manager, which must be initialized by the caller.

    Args:
        bot_name (str, optional): The name of the bot to get the summary for.
                                This name is used to ensure the DB connection
                                uses the correct schema.

    Returns:
        dict: A dictionary containing the performance summary.
    """
    logger.info(f"PerformanceService: Calculating performance summary for bot: {bot_name}...")
    total_usd_pnl = Decimal('0')
    total_btc_pnl = Decimal('0')
    total_treasury_btc = Decimal('0')
    sell_trade_count = 0

    try:
        # This will connect to the schema for the bot configured in the .env file
        db_manager = PostgresManager()

        # Get the mode ('trade', 'test', etc.) for the current bot.
        # This ensures we get a summary for the environment the user is running the script against.
        current_mode = config_manager.get('APP', 'mode', fallback='trade')
        logger.info(f"PerformanceService: Calculating summary for environment: '{current_mode}'")

        # Fetch only successfully closed 'sell' trades for the current environment.
        # This is the single source of truth for realized PnL.
        closed_sell_trades = db_manager.get_all_trades_in_range(
            mode=current_mode,
            order_type='sell',
            status='CLOSED'
        )

        if not closed_sell_trades:
            logger.warning(f"PerformanceService: No closed sell trades found for environment '{current_mode}'.")
            return {
                "sell_trade_count": 0,
                "total_usd_pnl": "0.0000",
                "total_btc_pnl": "0.00000000",
                "total_treasury_btc": "0.00000000"
            }

        sell_trade_count = len(closed_sell_trades)

        for trade in closed_sell_trades:
                # The loop now only iterates over confirmed, closed sell trades.
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
