# Ficheiro: src/core/confidence_manager.py (VERSÃO FINAL)

import pandas as pd
from src.config_manager import settings
from src.logger import logger

class ConfidenceManager:
    """
    Determina o limiar de confiança necessário para entrar num trade,
    ajustando-o dinamicamente com base no regime de mercado atual.
    """
    def __init__(self):
        self.base_threshold = settings.trading_strategy.confidence_threshold
        # Fatores de ajuste de confiança por regime de mercado (configurável)
        self.regime_adjustments = {
            # Em regimes de alta volatilidade, podemos ser um pouco menos exigentes
            'alta_volatilidade_bullish': 0.95, # Exige 95% do limiar base
            'alta_volatilidade_bearish': 1.10, # Exige 110% (mais seletivo)
            # Em regimes de baixa volatilidade, somos mais rigorosos
            'baixa_volatilidade_bullish': 1.00,
            'baixa_volatilidade_bearish': 1.20, # Exige 120% (muito seletivo)
            'default': 1.05
        }
        logger.info("✅ Gestor de Confiança Dinâmica inicializado.")

    def get_current_threshold(self, candle: pd.Series) -> float:
        """
        Retorna o limiar de confiança ajustado para a vela atual.
        """
        try:
            # O 'regime' é calculado pelo SituationalAwareness no data_pipeline
            # e já está presente na vela que recebemos.
            current_regime = candle.get('regime', 'default')
            adjustment_factor = self.regime_adjustments.get(current_regime, self.regime_adjustments['default'])
            
            adjusted_threshold = self.base_threshold * adjustment_factor
            
            logger.debug(f"Regime: '{current_regime}', Fator de Ajuste: {adjustment_factor:.2f}, Limiar Final: {adjusted_threshold:.2%}")
            
            return adjusted_threshold
            
        except Exception as e:
            logger.warning(f"Não foi possível determinar o regime de mercado. Usando limiar base. Erro: {e}")
            return self.base_threshold