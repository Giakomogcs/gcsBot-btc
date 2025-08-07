# src/core/optimizer.py (VERSÃO FINAL)

import optuna
import pandas as pd
from typing import Dict, Any

from jules_bot.utils.logger import logger
from jules_bot.bot.model_trainer import ModelTrainer
from jules_bot.bot.model_evaluator import ModelEvaluator

class Optimizer:
    """Usa o Optuna para encontrar os melhores hiperparâmetros para um modelo especialista."""

    def __init__(self, data: pd.DataFrame, specialist_name: str, specialist_features: list[str], n_trials: int):
        self.data = data
        self.specialist_name = specialist_name
        self.specialist_features = specialist_features
        self.n_trials = n_trials

    def _objective(self, trial: optuna.trial.Trial) -> float:
        """
        Função objetivo para o Optuna. Um 'trial' representa uma execução completa
        de treino e avaliação com um conjunto de hiperparâmetros.
        """
        # Sugere os hiperparâmetros para este trial
        params = {
            "objective": "binary",
            "metric": "binary_logloss",
            "n_estimators": trial.suggest_int("n_estimators", 100, 1000),
            "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.3),
            "num_leaves": trial.suggest_int("num_leaves", 20, 300),
            "max_depth": trial.suggest_int("max_depth", 3, 12),
            "min_child_samples": trial.suggest_int("min_child_samples", 5, 100),
            "feature_fraction": trial.suggest_float("feature_fraction", 0.4, 1.0),
            "bagging_fraction": trial.suggest_float("bagging_fraction", 0.4, 1.0),
            "bagging_freq": trial.suggest_int("bagging_freq", 1, 7),
            "verbose": -1
        }

        try:
            # Divide os dados para este trial
            train_data = self.data.sample(frac=0.8, random_state=42)
            val_data = self.data.drop(train_data.index)

            # Treina o modelo com os parâmetros sugeridos
            trainer = ModelTrainer(params=params, features=self.specialist_features)
            model, scaler = trainer.train(train_data)
            
            # Avalia o modelo nos dados de validação
            metrics = ModelEvaluator.evaluate(model, scaler, val_data, self.specialist_features)
            
            # O Optuna tentará maximizar esta métrica
            return metrics["profit_factor"]

        except Exception as e:
            logger.error(f"Trial falhou: {e}")
            return 0.0 # Retorna um mau resultado se o trial falhar

    def run(self) -> Dict[str, Any]:
        """Executa o processo de otimização."""
        logger.info(f"--- 🚀 INICIANDO OTIMIZAÇÃO PARA O ESPECIALISTA: {self.specialist_name} 🚀 ---")
        
        study = optuna.create_study(direction="maximize")
        study.optimize(self._objective, n_trials=self.n_trials)
        
        logger.info(f"Otimização concluída para '{self.specialist_name}'.")
        logger.info(f"Melhor Profit Factor: {study.best_value:.4f}")
        logger.info(f"Melhores Parâmetros: {study.best_params}")
        
        return study.best_params