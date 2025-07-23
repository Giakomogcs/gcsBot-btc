# src/treasury_manager.py

import pandas as pd
from src.logger import logger
from src.config import settings

class TreasuryManager:
    def __init__(self, btc_goal=0.1):
        self.btc_goal = btc_goal

    def track_progress(self, current_btc_holdings):
        progress = (current_btc_holdings / self.btc_goal) * 100
        logger.info(f"Progresso da Tesouraria: {current_btc_holdings:.8f}/{self.btc_goal:.8f} BTC ({progress:.2f}%)")

    def smart_accumulation(self, latest_data: pd.Series, trading_capital_usdt: float, session_wins: int, session_trades: int) -> float:
        """
        A smart accumulation strategy that buys a small amount of BTC every day.

        Args:
            latest_data: The latest data.
            trading_capital_usdt: The amount of USDT available for trading.
            session_wins: The number of wins in the current session.
            session_trades: The number of trades in the current session.

        Returns:
            The amount of USDT to use for buying BTC.
        """
        if not settings.DCA_IN_BEAR_MARKET_ENABLED or trading_capital_usdt < settings.DCA_MIN_CAPITAL_USDT:
            return 0.0

        # Calculate the win rate
        win_rate = session_wins / session_trades if session_trades > 0 else 0

        # Adjust the DCA amount based on the market regime and the bot's performance
        if 'market_regime' in latest_data:
            if 'BEAR' in latest_data['market_regime'] and win_rate > 0.5:
                return settings.DCA_DAILY_AMOUNT_USDT * 2
            elif 'BULL' in latest_data['market_regime'] and win_rate < 0.5:
                return settings.DCA_DAILY_AMOUNT_USDT / 2

        return settings.DCA_DAILY_AMOUNT_USDT

    def is_it_worth_it(self, latest_data):
        # Simple logic: Buy if the price is below the 50-day moving average, sell if it's above
        if latest_data['close'] < latest_data['sma_50']:
            return "BUY"
        elif latest_data['close'] > latest_data['sma_50']:
            return "SELL"
        else:
            return "HOLD"
