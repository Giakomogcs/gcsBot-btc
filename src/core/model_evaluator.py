# src/core/model_evaluator.py (VERSÃO FINAL)

import pandas as pd
import numpy as np
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score
from typing import Any, Dict

class ModelEvaluator:
    """Avalia a performance de um modelo treinado, focando em métricas financeiras."""

    @staticmethod
    def evaluate(model: Any, scaler: Any, data: pd.DataFrame, features: list[str]) -> Dict[str, float]:
        """
        Avalia o modelo em um conjunto de dados e retorna um dicionário de métricas.
        """
        if data.empty:
            return {"profit_factor": 0.0, "accuracy": 0.0, "trades": 0}

        X = data[features]
        y_true = data['target']
        
        X_scaled = scaler.transform(X)
        y_pred = model.predict(X_scaled)

        # Simula uma estratégia de trading simples para calcular o P&L
        # Assume que 'target' representa o retorno percentual se a previsão for correta
        # Nota: 'target_return' deveria ser uma coluna na sua features_master_table
        # Por agora, vamos simular um retorno fixo para testar a mecânica.
        
        # Cria um P&L simulado: +1% para acerto, -1% para erro
        simulated_pnl = np.where(y_pred == y_true, 0.01, -0.01)
        
        gross_profit = np.sum(simulated_pnl[simulated_pnl > 0])
        gross_loss = abs(np.sum(simulated_pnl[simulated_pnl < 0]))
        
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else 100.0

        return {
            "profit_factor": profit_factor,
            "accuracy": accuracy_score(y_true, y_pred),
            "precision": precision_score(y_true, y_pred, zero_division=0),
            "recall": recall_score(y_true, y_pred, zero_division=0),
            "f1_score": f1_score(y_true, y_pred, zero_division=0),
            "trades": len(data)
        }