# src/confidence_manager.py (VERSÃO 2.2 - Sensibilidade Otimizável)

import numpy as np
from src.logger import logger
from collections import deque

class AdaptiveConfidenceManager:
    """
    Gerencia dinamicamente o limiar de confiança para entrada em trades
    com base na performance de uma janela de trades recentes.
    """
    # <<< MUDANÇA 1: ADICIONAR O PARÂMETRO DE CLAMPING NO CONSTRUTOR >>>
    def __init__(self, initial_confidence: float, learning_rate: float = 0.05, min_confidence: float = 0.505, max_confidence: float = 0.85, window_size: int = 5, pnl_clamp_value: float = 0.02):
        self.initial_confidence = initial_confidence
        self.current_confidence = initial_confidence
        self.learning_rate = learning_rate
        self.min_confidence = min_confidence
        self.max_confidence = max_confidence
        self.trade_count = 0
        self.pnl_history = deque(maxlen=window_size)
        
        # <<< MUDANÇA 2: ARMAZENAR O VALOR DE CLAMP >>>
        self.pnl_clamp_value = abs(pnl_clamp_value) # Garante que o valor seja sempre positivo

        logger.debug(
            f"AdaptiveConfidenceManager inicializado: Confiança Inicial={initial_confidence:.3f}, "
            f"Janela={window_size}, Taxa Aprendizado={learning_rate:.3f}, "
            f"Clamp PnL=±{self.pnl_clamp_value:.2%}"
        )

    def update(self, pnl_percent: float):
        """
        Atualiza o limiar de confiança com base na média do resultado dos últimos trades.
        """
        self.trade_count += 1
        self.pnl_history.append(pnl_percent)
        
        mean_pnl = np.mean(self.pnl_history)
        
        # <<< MUDANÇA 3: USAR O VALOR DE CLAMP DINÂMICO >>>
        # O ajuste é proporcional ao PnL médio, limitado pelo valor otimizado.
        clamped_pnl = np.clip(mean_pnl, -self.pnl_clamp_value, self.pnl_clamp_value)
        
        adjustment = self.learning_rate * clamped_pnl
        new_confidence = self.current_confidence - adjustment
        
        self.current_confidence = np.clip(new_confidence, self.min_confidence, self.max_confidence)
        
        log_message = (
            f"🧠 Cérebro Tático (Trade #{self.trade_count}): "
            f"PnL Médio (últimos {len(self.pnl_history)})={mean_pnl:+.2%}. "
            f"Ajuste={-adjustment:.4f}. "
            f"Confiança alterada para {self.current_confidence:.3f}"
        )
        logger.debug(log_message)


    def get_confidence(self) -> float:
        """Retorna o limiar de confiança atual."""
        return self.current_confidence