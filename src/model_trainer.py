# src/model_trainer.py (VERSÃO 7.0 - FOCADO APENAS EM TREINO)

import pandas as pd
import numpy as np
from lightgbm import LGBMClassifier
from sklearn.preprocessing import StandardScaler
from numba import jit
from typing import Tuple, List, Any

from src.logger import logger, log_table

@jit(nopython=True)
def create_labels_triple_barrier(
    closes: np.ndarray, highs: np.ndarray, lows: np.ndarray, atr: np.ndarray,
    future_periods: int, profit_multiplier: float, stop_multiplier: float
) -> np.ndarray:
    """
    Implementação da Barreira Tripla com 3 classes de rótulos:
    - 1: Compra (barreira de lucro atingida)
    - 2: Venda (barreira de stop atingida)
    - 0: Neutro (tempo esgotado sem tocar nas barreiras)
    """
    n = len(closes)
    labels = np.zeros(n, dtype=np.int64)
    for i in range(n - future_periods):
        if atr[i] <= 1e-10: continue
        
        profit_barrier = closes[i] + (atr[i] * profit_multiplier)
        stop_barrier = closes[i] - (atr[i] * stop_multiplier)
        
        for j in range(1, future_periods + 1):
            future_high, future_low = highs[i + j], lows[i + j]
            
            if future_high >= profit_barrier:
                labels[i] = 1 # Lucro
                break
            if future_low <= stop_barrier:
                labels[i] = 2 # Prejuízo
                break
                
    return labels

class ModelTrainer:
    def train(self, data: pd.DataFrame, all_params: dict, feature_names: List[str]) -> Tuple[LGBMClassifier | None, StandardScaler | None]:
        """
        Recebe os dados JÁ PROCESSADOS, treina o modelo e retorna os artefatos.
        A engenharia de features foi removida e centralizada no DataManager.
        """
        if len(data) < 500:
            logger.warning(f"Dados insuficientes para treino ({len(data)} registros). Pulando.")
            return None, None

        logger.debug("Iniciando o processo de treino do modelo...")
        
        # Os dados já vêm com features e shift aplicado do DataManager
        df_processed = data.copy()

        future_periods = all_params.get('future_periods', 30)
        profit_mult = all_params.get('profit_mult', 2.0)
        stop_mult = all_params.get('stop_mult', 2.0)

        # A coluna 'atr' já existe e está correta
        labels_np = create_labels_triple_barrier(
            closes=df_processed['close'].to_numpy(), highs=df_processed['high'].to_numpy(),
            lows=df_processed['low'].to_numpy(), atr=df_processed['atr'].to_numpy(),
            future_periods=future_periods, profit_multiplier=profit_mult, stop_multiplier=stop_mult
        )
        y = pd.Series(labels_np, index=df_processed.index, name="label")
        
        X = df_processed[feature_names]

        # Checagem de sanidade para garantir que temos sinais de compra e venda
        counts = y.value_counts()
        if counts.get(1, 0) < 15 or counts.get(2, 0) < 15:
            logger.warning(f"Não há exemplos suficientes de compra(1) ou venda(2) para um treino confiável. Counts: {counts.to_dict()}")
            return None, None

        logger.info(f"Treinando modelo com {len(feature_names)} features.")
        log_table("Distribuição dos Labels no Treino", y.value_counts(normalize=True).reset_index(), headers=["Label", "Frequência"])
        
        scaler = StandardScaler()
        X_scaled = pd.DataFrame(scaler.fit_transform(X), index=X.index, columns=X.columns)
        
        # Filtra apenas os parâmetros que o LGBMClassifier aceita
        model_params = {k: v for k, v in all_params.items() if k in LGBMClassifier().get_params().keys()}
        
        model = LGBMClassifier(**model_params, random_state=42, n_jobs=-1, class_weight='balanced', verbosity=-1)
        model.fit(X_scaled, y)

        logger.debug("Treinamento do modelo concluído com sucesso.")
        
        return model, scaler