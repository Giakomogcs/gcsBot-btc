import asyncio
import json
import os
import sys
import typer
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Add project root to sys.path to allow imports from other directories
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from jules_bot.core.exchange_connector import ExchangeManager
from jules_bot.utils.logger import logger

def main(
    mode: str = typer.Argument(
        "test",
        help="The environment to get data for ('trade' or 'test')."
    )
):
    """
    Fetches and displays live wallet balances from the exchange.
    """
    if mode not in ["trade", "test"]:
        logger.error("Invalid mode specified. Please choose 'trade' or 'test'.")
        raise typer.Exit(code=1)

    logger.info(f"Gathering wallet balances for '{mode}' environment...")

    try:
        exchange_manager = ExchangeManager(mode=mode)
        symbol = "BTCUSDT"

        # 1. Fetch current price for USD value calculation
        current_price = exchange_manager.get_current_price(symbol)
        if current_price is None:
            logger.error(f"Could not fetch the current price for {symbol}.")
            raise typer.Exit(code=1)

        # 2. Fetch live wallet data
        wallet_balances = exchange_manager.get_account_balance()
        
        # 3. Ensure BTC and USDT are always present in the output
        processed_balances_dict = {
            'BTC': {'asset': 'BTC', 'free': '0.0', 'locked': '0.0', 'usd_value': 0.0},
            'USDT': {'asset': 'USDT', 'free': '0.0', 'locked': '0.0', 'usd_value': 0.0}
        }

        # Update the default structure with actual balances from the exchange
        for bal in wallet_balances:
            asset = bal.get('asset')
            if asset in processed_balances_dict:
                processed_balances_dict[asset] = bal # Replace default with actual
        
        # 4. Calculate USD value and create the final list
        processed_balances = []
        for asset, bal in processed_balances_dict.items():
            free = float(bal.get('free', 0))
            
            # Calculate USD value based on the FREE (available) balance
            if asset == 'BTC':
                bal['usd_value'] = free * current_price
            elif asset == 'USDT':
                bal['usd_value'] = free
            
            processed_balances.append(bal)

        # 5. Print the data as a JSON object
        print(json.dumps(processed_balances, indent=4, default=str))

        logger.info(f"Successfully retrieved wallet balances for '{mode}' environment.")

    except Exception as e:
        logger.error(f"A critical error occurred: {e}", exc_info=True)
        raise typer.Exit(code=1)

if __name__ == "__main__":
    typer.run(main)