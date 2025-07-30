# src/core/position_manager.py (VERSÃO FINAL E CORRETA)

import pandas as pd
from src.logger import logger

class PositionManager:
    def __init__(self, config):
        self.strategy_config = config.trading_strategy
        self.sizing_config = config.position_sizing
        
        self.profit_mult = self.strategy_config.triple_barrier.profit_mult
        self.stop_mult = self.strategy_config.triple_barrier.stop_mult
        self.time_limit_candles = self.strategy_config.triple_barrier.time_limit_candles
        
        self.open_positions = []

    def is_position_open(self):
        """Verifica se existe alguma posição aberta."""
        return len(self.open_positions) > 0

    def open_position(self, entry_candle, signal):
        """Abre uma nova posição baseada no sinal e na vela de entrada."""
        entry_price = entry_candle['close']
        atr = entry_candle['atr'] 

        if atr is None or atr == 0:
            logger.warning("ATR é zero ou nulo. Posição não aberta.")
            return

        if signal == 'LONG':
            take_profit_price = entry_price + (atr * self.profit_mult)
            stop_loss_price = entry_price - (atr * self.stop_mult)
        elif signal == 'SHORT':
            take_profit_price = entry_price - (atr * self.profit_mult)
            stop_loss_price = entry_price + (atr * self.stop_mult)
        else:
            return

        position = {
            'entry_price': entry_price,
            'entry_time': entry_candle.name,
            'signal': signal,
            'take_profit_price': take_profit_price,
            'stop_loss_price': stop_loss_price,
            # --- CORREÇÃO DO FUTUREWARNING ---
            'time_limit': entry_candle.name + pd.to_timedelta(self.time_limit_candles, unit='h'),
            'entry_candle_index': entry_candle.name,
            'status': 'OPEN'
        }
        self.open_positions.append(position)

    def check_and_close_positions(self, current_candle):
        """Verifica as posições abertas contra a vela atual para ver se alguma deve ser fechada."""
        closed_trades_summary = []
        
        for position in self.open_positions[:]:
            exit_reason = None
            exit_price = None

            if position['signal'] == 'LONG':
                if current_candle['high'] >= position['take_profit_price']:
                    exit_reason = 'TAKE_PROFIT'
                    exit_price = position['take_profit_price']
                elif current_candle['low'] <= position['stop_loss_price']:
                    exit_reason = 'STOP_LOSS'
                    exit_price = position['stop_loss_price']

            elif position['signal'] == 'SHORT':
                if current_candle['low'] <= position['take_profit_price']:
                    exit_reason = 'TAKE_PROFIT'
                    exit_price = position['take_profit_price']
                elif current_candle['high'] >= position['stop_loss_price']:
                    exit_reason = 'STOP_LOSS'
                    exit_price = position['stop_loss_price']

            # --- CORREÇÃO DO KEYERROR ---
            # O timestamp agora é o NOME (índice) da vela, não uma coluna.
            if not exit_reason and current_candle.name >= position['time_limit']:
                exit_reason = 'TIME_LIMIT'
                exit_price = current_candle['close']

            if exit_reason:
                pnl = (exit_price - position['entry_price']) if position['signal'] == 'LONG' else (position['entry_price'] - exit_price)
                
                trade_summary = {
                    'entry_time': position['entry_time'],
                    'exit_time': current_candle.name, 
                    'signal': position['signal'],
                    'entry_price': position['entry_price'],
                    'exit_price': exit_price,
                    'pnl': pnl,
                    'exit_reason': exit_reason
                }
                closed_trades_summary.append(trade_summary)
                
                self.open_positions.remove(position)

        return closed_trades_summary
        
    def update_open_positions(self, current_candle):
        """Mantido para compatibilidade e futuras implementações (ex: trailing stop)."""
        pass