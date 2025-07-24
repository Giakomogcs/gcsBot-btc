# src/core/model_trainer.py

import pandas as pd
import numpy as np
from lightgbm import LGBMClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split
from numba import jit
from typing import Optional, Tuple, List, Any, Dict

# Resolução de Path
import sys, os
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.logger import logger
from src.config_manager import settings
# from src.core.feature_selector import FeatureSelector # Desativado por agora
# from src.core.model_evaluator import ModelEvaluator # Desativado por agora

@jit(nopython=True)
def create_labels_triple_barrier(
    closes: np.ndarray, highs: np.ndarray, lows: np.ndarray, atr: np.ndarray,
    future_periods: int, profit_multiplier: float, stop_multiplier: float
) -> np.ndarray:
    """Cria labels binários (1 para compra, 0 para não comprar)."""
    n = len(closes)
    labels = np.zeros(n, dtype=np.int64)
    for i in range(n - future_periods):
        if atr[i] <= 1e-10: continue
        
        profit_barrier = closes[i] + (atr[i] * profit_multiplier)
        stop_barrier = closes[i] - (atr[i] * stop_multiplier)
        
        for j in range(1, future_periods + 1):
            future_high, future_low = highs[i + j], lows[i + j]
            if future_high >= profit_barrier:
                labels[i] = 1 # Sinal de COMPRA
                break
            if future_low <= stop_barrier:
                labels[i] = 0 # Prejuízo ou lateral, não é uma boa oportunidade de compra
                break
    return labels

class ModelTrainer:
    """
    Treina e avalia modelos de machine learning.
    Agora com capacidade de backtest para o otimizador.
    """
    def __init__(self) -> None:
        pass # self.feature_selector = FeatureSelector() # Reativaremos depois

    def train(self, data: pd.DataFrame, params: Dict[str, Any], feature_names: List[str]) -> Tuple[Optional[LGBMClassifier], Optional[StandardScaler]]:
        """
        Lógica de treino principal.
        Recebe os dados e um conjunto específico de features para treinar.
        """
        # ... (A lógica de treino que tínhamos antes, mas simplificada)
        if len(data) < 500:
            logger.warning(f"Dados insuficientes para treino ({len(data)} registros).")
            return None, None

        df_processed = data.copy()

        labels_np = create_labels_triple_barrier(
            closes=df_processed['close'].to_numpy(), highs=df_processed['high'].to_numpy(),
            lows=df_processed['low'].to_numpy(), atr=df_processed['atr'].to_numpy(),
            future_periods=settings.model_params.future_periods,
            profit_multiplier=settings.model_params.profit_mult,
            stop_multiplier=settings.model_params.stop_mult
        )
        y = pd.Series(labels_np, index=df_processed.index, name="label")
        X = df_processed[feature_names]

        if y.value_counts().get(1, 0) < 15:
            logger.warning(f"Não há exemplos suficientes de compra (label 1).")
            return None, None

        scaler = StandardScaler()
        X_scaled = pd.DataFrame(scaler.fit_transform(X), index=X.index, columns=X.columns)
        
        model = LGBMClassifier(**params)
        model.fit(X_scaled, y)
        
        return model, scaler

    def train_and_backtest_for_optimization(self, data: pd.DataFrame, params: Dict[str, Any], feature_names: List[str]) -> float:
        """
        Função para o otimizador. Treina, faz um backtest simples e retorna um score.
        """
        if len(data) < 1000:
            return 0.0
        
        train_data, test_data = train_test_split(data, test_size=0.3, shuffle=False)
        model, scaler = self.train(train_data, params, feature_names)

        if model is None or scaler is None:
            return 0.0

        X_test = test_data[feature_names]
        
        # <<< --- A CORREÇÃO ESTÁ AQUI --- >>>
        # Transformamos o resultado do scaler de volta num DataFrame com os nomes das colunas
        X_test_scaled = pd.DataFrame(scaler.transform(X_test), index=X_test.index, columns=X_test.columns)
        # <<< --- FIM DA CORREÇÃO --- >>>
        
        y_test_real_returns = test_data['close'].pct_change().shift(-1).fillna(0)
        predictions = model.predict(X_test_scaled)
        
        pnl = np.sum(y_test_real_returns[predictions == 1])
        score = pnl * 100
        num_trades = np.sum(predictions == 1)

        if num_trades < 10:
            return 0.0

        return score