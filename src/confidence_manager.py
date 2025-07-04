# src/confidence_manager.py (VERSÃO 2.0 - COM JANELA DE PNL)

import numpy as np
from src.logger import logger
from collections import deque # <<< PASSO 1: Importar deque

class AdaptiveConfidenceManager:
    """
    Gerencia dinamicamente o limiar de confiança para entrada em trades
    com base na performance de uma janela de trades recentes.
    """
    def __init__(self, initial_confidence: float, learning_rate: float = 0.05, min_confidence: float = 0.505, max_confidence: float = 0.85, window_size: int = 5):
        """
        Args:
            initial_confidence (float): O limiar de confiança inicial, otimizado pelo Optuna.
            learning_rate (float): Quão agressivamente a confiança se ajusta.
            min_confidence (float): O valor mínimo que a confiança pode atingir.
            max_confidence (float): O valor máximo que a confiança pode atingir.
            window_size (int): O número de trades recentes a serem considerados para o ajuste.
        """
        self.initial_confidence = initial_confidence
        self.current_confidence = initial_confidence
        self.learning_rate = learning_rate
        self.min_confidence = min_confidence
        self.max_confidence = max_confidence
        self.trade_count = 0
        
        # <<< PASSO 2: Inicializar o deque para armazenar o histórico de PnL >>>
        self.pnl_history = deque(maxlen=window_size)
        
        logger.debug(f"AdaptiveConfidenceManager inicializado com confiança inicial de {initial_confidence:.3f} e janela de {window_size} trades.")

    def update(self, pnl_percent: float):
        """
        Atualiza o limiar de confiança com base na média do resultado dos últimos trades.
        """
        self.trade_count += 1
        self.pnl_history.append(pnl_percent)
        
        # <<< PASSO 3: Calcular a média do PnL do histórico >>>
        # Usa a média do histórico em vez do PnL de um único trade
        mean_pnl = np.mean(self.pnl_history)
        
        # O ajuste é proporcional ao PnL MÉDIO, com um limite para evitar mudanças bruscas
        clamped_pnl = np.clip(mean_pnl, -0.02, 0.02)
        
        # A fórmula central permanece, mas agora usa o PnL médio
        adjustment = self.learning_rate * clamped_pnl
        new_confidence = self.current_confidence - adjustment
        
        # Garante que a nova confiança permaneça dentro dos limites definidos
        self.current_confidence = np.clip(new_confidence, self.min_confidence, self.max_confidence)
        
        logger.debug(
            f"Trade #{self.trade_count}: PnL Médio (últimos {len(self.pnl_history)} trades)={mean_pnl:+.2%}. "
            f"Confiança ajustada para {self.current_confidence:.3f}"
        )

    def get_confidence(self) -> float:
        """Retorna o limiar de confiança atual."""
        return self.current_confidence