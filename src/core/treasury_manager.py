# src/treasury_manager.py

from src.logger import logger

class TreasuryManager:
    def __init__(self, btc_goal=0.1):
        self.btc_goal = btc_goal

    def track_progress(self, current_btc_holdings):
        progress = (current_btc_holdings / self.btc_goal) * 100
        logger.info(f"Progresso da Tesouraria: {current_btc_holdings:.8f}/{self.btc_goal:.8f} BTC ({progress:.2f}%)")

    def smart_accumulation(self, latest_data, current_usdt_balance):
        # Buy BTC for the treasury when the price is below the 200-day moving average
        if latest_data['close'] < latest_data['sma_200']:
            amount_to_buy_usdt = current_usdt_balance * 0.1 # Buy with 10% of the available USDT
            return amount_to_buy_usdt
        return 0

    def is_it_worth_it(self, latest_data):
        # Simple logic: Buy if the price is below the 50-day moving average, sell if it's above
        if latest_data['close'] < latest_data['sma_50']:
            return "BUY"
        elif latest_data['close'] > latest_data['sma_50']:
            return "SELL"
        else:
            return "HOLD"
