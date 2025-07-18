# src/confidence_manager.py (VERSÃO 2.3 - REATIVIDADE DINÂMICA)

import numpy as np
from src.logger import logger
from collections import deque

class AdaptiveConfidenceManager:
    """
    Gerencia dinamicamente o limiar de confiança para entrada em trades
    com base na performance de uma janela de trades recentes.
    Agora com reatividade dinâmica baseada na magnitude do PnL.
    """
    # === MUDANÇA 1: Adicionar novo parâmetro de reatividade ===
    def __init__(self, initial_confidence: float, learning_rate: float = 0.05, 
                 min_confidence: float = 0.505, max_confidence: float = 0.85, 
                 window_size: int = 5, pnl_clamp_value: float = 0.02,
                 reactivity_multiplier: float = 5.0):
        self.initial_confidence = initial_confidence
        self.current_confidence = initial_confidence
        self.learning_rate = learning_rate
        self.min_confidence = min_confidence
        self.max_confidence = max_confidence
        self.trade_count = 0
        self.pnl_history = deque(maxlen=window_size)
        self.pnl_clamp_value = abs(pnl_clamp_value)
        self.reactivity_multiplier = reactivity_multiplier # Armazena o novo parâmetro

        logger.debug(
            f"AdaptiveConfidenceManager inicializado: Confiança Inicial={initial_confidence:.3f}, "
            f"Janela={window_size}, Taxa Aprendizado={learning_rate:.3f}, "
            f"Clamp PnL=±{self.pnl_clamp_value:.2%}, Reatividade={self.reactivity_multiplier}"
        )

    def update(self, pnl_percent: float):
        """
        Atualiza o limiar de confiança. O ajuste agora é amplificado pela
        magnitude da média de PnL recente.
        """
        self.trade_count += 1
        self.pnl_history.append(pnl_percent)
        
        mean_pnl = np.mean(self.pnl_history)
        
        clamped_pnl = np.clip(mean_pnl, -self.pnl_clamp_value, self.pnl_clamp_value)
        
        # === MUDANÇA 2: Lógica de ajuste dinâmico ===
        # O fator de reatividade amplifica o ajuste com base na magnitude do PnL médio.
        # Resultados fortes (positivos ou negativos) causam uma reação mais forte.
        reactivity_factor = 1.0 + (abs(clamped_pnl) * self.reactivity_multiplier)
        
        adjustment = self.learning_rate * clamped_pnl * reactivity_factor
        
        new_confidence = self.current_confidence - adjustment
        
        self.current_confidence = np.clip(new_confidence, self.min_confidence, self.max_confidence)
        
        log_message = (
            f"🧠 Cérebro Tático (Trade #{self.trade_count}): "
            f"PnL Médio (últimos {len(self.pnl_history)})={mean_pnl:+.2%}. "
            f"Ajuste={-adjustment:.4f} (Reatividade: {reactivity_factor:.2f}x). " # Log da reatividade
            f"Confiança alterada para {self.current_confidence:.3f}"
        )
        logger.debug(log_message)

    def get_confidence(self) -> float:
        """Retorna o limiar de confiança atual."""
        return self.current_confidence