# src/core/model_trainer.py (VERSÃO FINAL)

import pandas as pd
from lightgbm import LGBMClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split
from typing import Tuple, Any, Dict

from gcs_bot.utils.logger import logger

class ModelTrainer:
    """Responsável por treinar um único modelo de IA com um conjunto de dados e parâmetros."""

    def __init__(self, params: Dict[str, Any], features: list[str]):
        self.params = params
        self.features = features
        self.model = LGBMClassifier(**params)
        self.scaler = StandardScaler()

    def train(self, data: pd.DataFrame) -> Tuple[Any, Any]:
        """
        Treina o modelo e o scaler com os dados fornecidos.

        Args:
            data (pd.DataFrame): O DataFrame contendo as features e a coluna 'target'.

        Returns:
            Tuple[Any, Any]: O modelo treinado e o scaler ajustado.
        """
        if 'target' not in data.columns:
            raise ValueError("A coluna 'target' é necessária para o treinamento.")
        
        X = data[self.features]
        y = data['target']

        # Separa os dados em treino e teste para evitar overfitting durante o treino
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, random_state=42, stratify=y
        )

        logger.debug(f"Treinando modelo com {len(X_train)} amostras.")
        
        # Ajusta o scaler nos dados de treino e transforma ambos
        X_train_scaled = self.scaler.fit_transform(X_train)
        
        # Treina o modelo
        self.model.fit(X_train_scaled, y_train)
        
        return self.model, self.scaler