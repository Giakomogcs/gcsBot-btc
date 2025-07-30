# src/core/optimizer.py (VERSÃO CORRIGIDA E CENTRALIZADA)

import warnings
import optuna
import pandas as pd
import numpy as np
import json
import os
import joblib
import datetime # Import datetime

from src.core.model_trainer import ModelTrainer
from src.logger import logger
from src.config_manager import settings # Nossa fonte única da verdade

import logging

# Ignora TODOS os UserWarning (forma mais ampla)
warnings.filterwarnings("ignore", category=UserWarning)
# Configura o logger do LightGBM para mostrar apenas erros críticos
logging.getLogger('lightgbm').setLevel(logging.ERROR)
logging.getLogger('lightgbm').setLevel(logging.WARNING)

class WalkForwardOptimizer:
    def __init__(self, full_data: pd.DataFrame):
        self.full_data = full_data
        self.trainer = ModelTrainer()
        # --- INÍCIO DA CORREÇÃO 1: LER CONFIGURAÇÕES DO 'settings' ---
        self.optimizer_settings = settings.optimizer
        self.n_trials = self.optimizer_settings.n_trials
        
        # A definição dos especialistas e suas features agora vem do config.yml
        self.specialist_definitions = {
            name: spec.features 
            for name, spec in settings.trading_strategy.models.specialists.items()
        }
        logger.info(f"Otimizador configurado para os especialistas: {list(self.specialist_definitions.keys())}")
        # --- FIM DA CORREÇÃO 1 ---

    def _objective(self, trial: optuna.trial.Trial, data_for_objective: pd.DataFrame, specialist_features: list) -> float:
        """A função objetivo que o Optuna tentará maximizar."""
        # ... (NENHUMA MUDANÇA NESTA FUNÇÃO) ...
        params = {
            'objective': 'binary', 'metric': 'binary_logloss', 'verbosity': -1, 'boosting_type': 'gbdt',
            'n_estimators': trial.suggest_int('n_estimators', 100, 1000, log=True),
            'learning_rate': trial.suggest_float('learning_rate', 0.01, 0.3, log=True),
            'num_leaves': trial.suggest_int('num_leaves', 20, 300),
            'max_depth': trial.suggest_int('max_depth', 3, 12),
            'min_child_samples': trial.suggest_int('min_child_samples', 5, 100),
            'feature_fraction': trial.suggest_float('feature_fraction', 0.4, 1.0),
            'bagging_fraction': trial.suggest_float('bagging_fraction', 0.4, 1.0),
            'bagging_freq': trial.suggest_int('bagging_freq', 1, 7),
            'lambda_l1': trial.suggest_float('lambda_l1', 1e-8, 10.0, log=True),
            'lambda_l2': trial.suggest_float('lambda_l2', 1e-8, 10.0, log=True),
        }
        
        score = self.trainer.train_and_backtest_for_optimization(
            data=data_for_objective,
            params=params,
            feature_names=specialist_features
        )
        return score

    def run_optimization_for_situation(self, situation_name: str, data: pd.DataFrame) -> None:
        logger.info(f"\n{'='*20} Iniciando otimização para: {situation_name.upper()} {'='*20}")
        
        # --- INÍCIO DA CORREÇÃO 2: CAMINHO DOS MODELOS VIA 'settings' ---
        situation_models_path = settings.trading_strategy.models.models_path
        os.makedirs(situation_models_path, exist_ok=True)
        # --- FIM DA CORREÇÃO 2 ---

        for specialist_name, specialist_features in self.specialist_definitions.items():
            # Verifica se todas as features necessárias existem no DataFrame
            if not all(feature in data.columns for feature in specialist_features):
                logger.error(f"Features faltando para o especialista '{specialist_name}'. Pulando otimização.")
                logger.error(f"Features necessárias: {specialist_features}")
                logger.error(f"Features disponíveis: {data.columns.to_list()}")
                continue
            
            logger.info(f"--- Otimizando especialista: '{specialist_name}' ---")
            study = optuna.create_study(direction="maximize")
            objective_func = lambda trial: self._objective(trial, data, specialist_features)
            study.optimize(objective_func, n_trials=self.n_trials)

            try:
                best_trial = study.best_trial
                best_score = best_trial.value
                best_params = best_trial.params
                logger.info(f"🏆 Otimização de '{specialist_name}' concluída. Melhor Score: {best_score:.4f}")

                # --- INÍCIO DA CORREÇÃO 3: LIMIAR DE QUALIDADE VIA 'settings' ---
                if best_score > self.optimizer_settings.quality_threshold:
                # --- FIM DA CORREÇÃO 3 ---
                    logger.info(f"   -> Score excelente! Treinando e salvando modelo final...")
                    final_model = self.trainer.train(data, best_params, specialist_features)
                    
                    if final_model:
                        joblib.dump(final_model, os.path.join(situation_models_path, f"model_{specialist_name}.joblib"))
                        
                        artefact_info = {
                            "best_params": best_params, "best_score": best_score,
                            "feature_names": specialist_features,
                            "trained_at": datetime.datetime.now().isoformat()
                        }
                        with open(os.path.join(situation_models_path, f"params_{specialist_name}.json"), 'w') as f:
                            json.dump(artefact_info, f, indent=4)
                        logger.info(f"   -> ✅ Modelo e Parâmetros para '{specialist_name}' salvos com sucesso!")
                else:
                    logger.warning(f"   -> Score de {best_score:.4f} não atingiu o limiar de qualidade ({self.optimizer_settings.quality_threshold}). Modelo não foi salvo.")

            except ValueError:
                logger.warning(f"❌ Nenhum trial concluído com sucesso para o especialista '{specialist_name}'.")

    def run(self) -> None:
        """Executa o processo de otimização completo."""
        logger.info("\n" + "="*80 + "\n--- 🚀 INICIANDO PROCESSO DE OTIMIZAÇÃO DA MENTE-COLMEIA 🚀 ---\n" + "="*80)
        optuna.logging.set_verbosity(optuna.logging.WARNING)
        self.run_optimization_for_situation("all_data", self.full_data)
        logger.info("\n" + "="*80 + "\n--- ✅ PROCESSO DE OTIMIZAÇÃO CONCLUÍDO ✅ ---\n" + "="*80)


if __name__ == '__main__':
    from src.data_manager import DataManager 
    
    logger.info("Carregando dados para o teste do otimizador...")
    data_manager = DataManager()
    full_dataframe = data_manager.read_data_from_influx(
        measurement="features_master_table",
        start_date=settings.backtest.start_date
    )

    if not full_dataframe.empty:
        optimizer = WalkForwardOptimizer(full_data=full_dataframe)
        optimizer.run()
    else:
        logger.error("Nenhuma feature foi carregada da 'features_master_table'. Execute o data_pipeline primeiro.")