# Ficheiro: src/core/position_manager.py (VERSÃO FINAL E AUTÓNOMA)

import pandas as pd
import uuid
from datetime import datetime
import json

from src.logger import logger
from src.config_manager import settings
# --- IMPORTAÇÃO CORRETA ---
# Importamos a CLASSE, não um objeto
from src.database.database_manager import DatabaseManager

class PositionManager:
    def __init__(self, config):
        self.config = config
        # --- ARQUITETURA CORRETA ---
        # O PositionManager agora cria e gere a sua própria conexão com o DB,
        # seguindo o mesmo padrão do seu DataManager.
        self.db_manager = DatabaseManager(
            url=self.config.database.url,
            token=self.config.database.token,
            org=self.config.database.org,
            bucket=self.config.database.bucket
        )
        
        self.position_config = self.config.position_management
        self.strategy_config = self.config.trading_strategy.triple_barrier
        self.first_entry_confidence_factor = self.config.backtest.first_entry_confidence_factor
        self.buy_the_dip_trigger_percent = self.config.backtest.buy_the_dip_trigger_percent / 100

    def get_open_positions(self) -> list:
        return self.db_manager.get_open_trades()

    def check_for_entry(self, candle: pd.Series, signal: str, confidence: float):
        open_positions = self.get_open_positions()
        open_trades_count = len(open_positions)
        max_trades = self.position_config.max_concurrent_trades

        if open_trades_count >= max_trades:
            return

        if open_trades_count == 0:
            required_confidence = self.config.trading_strategy.confidence_threshold * self.first_entry_confidence_factor
            if signal == "BUY" and confidence >= required_confidence:
                logger.info(f"ESTRATÉGIA 'ENTRAR NO JOGO': Condições atingidas. Confiança: {confidence:.2%}, Limiar Ajustado: {required_confidence:.2%}")
                self.open_position(candle)
            return

        if open_trades_count > 0:
            last_trade_price = sorted(open_positions, key=lambda x: x['entry_time'], reverse=True)[0]['entry_price']
            current_price = candle['close']
            price_change_percent = (current_price - last_trade_price) / last_trade_price

            if price_change_percent <= self.buy_the_dip_trigger_percent:
                logger.info(f"ESTRATÉGIA 'COMPRAR NA BAIXA': Preço caiu {price_change_percent:.2%}. Comprando mais.")
                self.open_position(candle, is_dca=True)
            return

    def open_position(self, candle: pd.Series, is_dca: bool = False):
        try:
            entry_price = candle['close']
            atr = candle['atr_14']
            if pd.isna(atr) or atr == 0: return

            trade_data = {
                "entry_price": entry_price,
                "quantity": 1.0, # O dimensionamento é tratado pelo backtester
                "entry_reason": "DCA" if is_dca else "INITIAL_ENTRY",
                "stop_loss_price": entry_price - (atr * self.strategy_config.stop_mult),
                "profit_target_price": entry_price + (atr * self.strategy_config.profit_mult),
                "entry_time": pd.to_datetime(candle.name).to_pydatetime()
            }
            self.db_manager.save_new_trade(trade_data)
        except Exception as e:
            logger.error(f"Erro ao abrir posição: {e}", exc_info=True)

    def check_and_close_positions(self, candle: pd.Series):
        closed_trades = []
        current_price = candle['close']
        open_positions = self.get_open_positions()
        if not open_positions:
            return []

        for trade in open_positions:
            exit_reason = None
            if current_price >= trade['profit_target_price']: exit_reason = 'TAKE_PROFIT'
            elif current_price <= trade['stop_loss_price']: exit_reason = 'STOP_LOSS'
            
            if exit_reason:
                pnl = (current_price - trade['entry_price']) * trade['quantity']
                pnl_percent = (pnl / (trade['entry_price'] * trade['quantity'])) * 100
                
                closed_trade_data = trade.copy()
                closed_trade_data.update({
                    "status": "CLOSED_PROFIT" if pnl > 0 else "CLOSED_LOSS",
                    "exit_price": current_price,
                    "exit_time": pd.to_datetime(candle.name).to_pydatetime(),
                    "exit_reason": exit_reason,
                    "pnl_usd": pnl,
                    "pnl_percentage": pnl_percent
                })
                
                if self.db_manager.update_closed_trade(closed_trade_data):
                    closed_trades.append(closed_trade_data)
        return closed_trades

    def __del__(self):
        """ Garante que a conexão com o DB seja fechada. """
        if hasattr(self, 'db_manager') and self.db_manager:
            self.db_manager.close()