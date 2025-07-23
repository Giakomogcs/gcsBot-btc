# src/model_trainer.py (VERSÃO 7.1 - FOCADO EM CLASSIFICAÇÃO BINÁRIA)

from datetime import datetime, timezone
import pandas as pd
import numpy as np
from lightgbm import LGBMClassifier
from sklearn.preprocessing import StandardScaler
from numba import jit
from typing import Optional, Tuple, List, Any, Dict

from src.logger import logger, log_table
from src.core.feature_selector import FeatureSelector
from src.database import Database
from src.core.model_evaluator import ModelEvaluator

@jit(nopython=True)
def create_labels_triple_barrier(
    closes: np.ndarray, highs: np.ndarray, lows: np.ndarray, atr: np.ndarray,
    future_periods: int, profit_multiplier: float, stop_multiplier: float
) -> np.ndarray:
    """
    Creates labels for the triple barrier method.

    Args:
        closes: A numpy array with the close prices.
        highs: A numpy array with the high prices.
        lows: A numpy array with the low prices.
        atr: A numpy array with the ATR values.
        future_periods: The number of future periods to consider.
        profit_multiplier: The profit multiplier.
        stop_multiplier: The stop loss multiplier.

    Returns:
        A numpy array with the labels.
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
                labels[i] = 1 # Sinal de COMPRA
                break
            # === MUDANÇA 1: Simplificação para Classificação Binária ===
            if future_low <= stop_barrier:
                labels[i] = 0 # Prejuízo é uma má oportunidade, logo 0.
                break
                
    return labels

class ModelTrainer:
    """A class to train the model."""

    def __init__(self) -> None:
        """Initializes the ModelTrainer class."""
        self.feature_selector = FeatureSelector()
        # 2. CREATE A DATABASE INSTANCE FOR THE TRAINER
        self.db = Database()


    def train(self, data: pd.DataFrame, all_params: Dict[str, Any], feature_names: List[str], base_model: Optional[LGBMClassifier] = None) -> Tuple[Optional[LGBMClassifier], Optional[StandardScaler], Optional[List[str]]]:
        """
        Trains the model.

        Args:
            data: The data to train the model on.
            all_params: The parameters for the model.
            feature_names: The names of the features to use.
            base_model: The base model to use for training.

        Returns:
            A tuple with the trained model, the scaler, and the list of selected features.
        """
        if len(data) < 500:
            logger.warning(f"Dados insuficientes para treino ({len(data)} registros). Pulando.")
            # 2. UPDATE THE RETURN STATEMENT FOR FAILURE
            return None, None, None

        logger.debug("Iniciando o processo de treino do modelo...")
        
        df_processed = data.copy()

        future_periods = all_params.get('future_periods', 30)
        profit_mult = all_params.get('profit_mult', 2.0)
        stop_mult = all_params.get('stop_mult', 2.0)

        labels_np = create_labels_triple_barrier(
            closes=df_processed['close'].to_numpy(), highs=df_processed['high'].to_numpy(),
            lows=df_processed['low'].to_numpy(), atr=df_processed['atr'].to_numpy(),
            future_periods=future_periods, profit_multiplier=profit_mult, stop_multiplier=stop_mult
        )
        y = pd.Series(labels_np, index=df_processed.index, name="label")
        
        X = df_processed[feature_names]

        selected_features = self.feature_selector.select_features(X, y)
        X = X[selected_features]

        # === MUDANÇA 2: Atualização da Checagem de Sanidade ===
        counts = y.value_counts()
        # Agora só precisamos checar se há exemplos de compra (label 1)
        if counts.get(1, 0) < 15:
            logger.warning(f"Não há exemplos suficientes de compra (label 1) para um treino confiável. Counts: {counts.to_dict()}")
            # 3. UPDATE THE RETURN STATEMENT FOR FAILURE
            return None, None, None

        logger.info(f"Treinando modelo com {len(feature_names)} features.")
        log_table("Distribuição dos Labels no Treino", y.value_counts(normalize=True).reset_index(), headers=["Label", "Frequência"])
        
        scaler = StandardScaler()
        X_scaled = pd.DataFrame(scaler.fit_transform(X), index=X.index, columns=X.columns)
        
        model_params = {k: v for k, v in all_params.items() if k in LGBMClassifier().get_params().keys()}
        
        if base_model:
            model = LGBMClassifier(**model_params, random_state=42, n_jobs=-1, class_weight='balanced', verbosity=-1)
            model.fit(X_scaled, y, init_model=base_model)
        else:
            model = LGBMClassifier(**model_params, random_state=42, n_jobs=-1, class_weight='balanced', verbosity=-1)
            model.fit(X_scaled, y)

        logger.debug("Treinamento do modelo concluído com sucesso.")

        
        evaluator = ModelEvaluator(model, scaler, df_processed, selected_features, y)
        metrics, _ = evaluator.evaluate()

        # Log metrics to database
        metrics_df = pd.DataFrame([metrics])
        metrics_df['timestamp'] = datetime.now(timezone.utc)
        metrics_df['model_name'] = all_params.get('model_name', 'default')
        
        # 3. USE THE TRAINER'S OWN DB CONNECTION
        # This was the line causing the crash.
        self.db.insert_dataframe(metrics_df, 'model_metrics')

        # 5. UPDATE THE FINAL RETURN STATEMENT
        return model, scaler, selected_features

    def train_base_model(self, data: pd.DataFrame, all_params: Dict[str, Any], feature_names: List[str]) -> Optional[LGBMClassifier]:
        """
        Trains a base model on the entire dataset.

        Args:
            data: The data to train the model on.
            all_params: The parameters for the model.
            feature_names: The names of the features to use.

        Returns:
            The trained base model.
        """
        if len(data) < 500:
            logger.warning(f"Dados insuficientes para treino ({len(data)} registros). Pulando.")
            return None

        logger.info("Training base model...")

        df_processed = data.copy()

        future_periods = all_params.get('future_periods', 30)
        profit_mult = all_params.get('profit_mult', 2.0)
        stop_mult = all_params.get('stop_mult', 2.0)

        labels_np = create_labels_triple_barrier(
            closes=df_processed['close'].to_numpy(), highs=df_processed['high'].to_numpy(),
            lows=df_processed['low'].to_numpy(), atr=df_processed['atr'].to_numpy(),
            future_periods=future_periods, profit_multiplier=profit_mult, stop_multiplier=stop_mult
        )
        y = pd.Series(labels_np, index=df_processed.index, name="label")

        X = df_processed[feature_names]

        counts = y.value_counts()
        if counts.get(1, 0) < 15:
            logger.warning(f"Não há exemplos suficientes de compra (label 1) para um treino confiável. Counts: {counts.to_dict()}")
            return None

        logger.info(f"Treinando modelo com {len(feature_names)} features.")
        log_table("Distribuição dos Labels no Treino", y.value_counts(normalize=True).reset_index(), headers=["Label", "Frequência"])

        scaler = StandardScaler()
        X_scaled = pd.DataFrame(scaler.fit_transform(X), index=X.index, columns=X.columns)

        model_params = {k: v for k, v in all_params.items() if k in LGBMClassifier().get_params().keys()}

        model = LGBMClassifier(**model_params, random_state=42, n_jobs=-1, class_weight='balanced', verbosity=-1)
        model.fit(X_scaled, y)

        logger.info("Base model trained.")
        
        return model