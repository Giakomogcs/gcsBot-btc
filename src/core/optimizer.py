# src/core/optimizer.py

import optuna
import pandas as pd
import numpy as np
import json
import os
import gc
import joblib
from collections import defaultdict

# Resolução de Path
import sys
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.data_manager import DataManager
from src.core.model_trainer import ModelTrainer
from src.logger import logger
from src.config_manager import settings

class WalkForwardOptimizer:
    """
    Orquestra a otimização Walk-Forward para um TIME de modelos especialistas.
    """
    def __init__(self, full_data: pd.DataFrame):
        self.full_data = full_data
        self.trainer = ModelTrainer()
        self.n_trials = settings.optimizer.n_trials_for_cycle
        self.optimization_summary = {}

        # Definição das personalidades dos especialistas
        self.specialist_definitions = {
            "price_action": [
                'atr', 'bb_width', 'bb_pband', 'price_change_1m', 'price_change_5m', 
                'momentum_10m', 'volatility_ratio'
            ],
            "quant_classic": [
                'rsi', 'macd_diff', 'stoch_osc', 'adx', 'adx_power', 'cci', 'williams_r',
                'cvd', 'cvd_short_term'
            ],
            "macro_hedger": [
                'dxy_close_change', 'vix_close_change', 'gold_close_change',
                'tnx_close_change', 'btc_dxy_corr_30d', 'btc_vix_corr_30d'
            ]
        }

    def _objective(self, trial: optuna.trial.Trial, data_for_objective: pd.DataFrame, specialist_features: list) -> float:
        """A função objetivo que o Optuna tentará maximizar."""
        params = {
            'objective': 'binary',
            'metric': 'binary_logloss',
            'verbosity': -1,
            'boosting_type': 'gbdt',
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
        """
        Executa a otimização e SALVA os melhores modelos para cada especialista.
        """
        logger.info(f"\n{'='*20} Iniciando otimização para: {situation_name.upper()} {'='*20}")
        
        situation_models_path = os.path.join(settings.data_paths.data_dir, situation_name)
        os.makedirs(situation_models_path, exist_ok=True)

        for specialist_name, specialist_features in self.specialist_definitions.items():
            logger.info(f"--- Otimizando especialista: '{specialist_name}' ---")

            study = optuna.create_study(direction="maximize")
            objective_func = lambda trial: self._objective(trial, data, specialist_features)
            study.optimize(objective_func, n_trials=self.n_trials)

            try:
                best_trial = study.best_trial
                best_score = best_trial.value
                best_params = best_trial.params
                logger.info(f"🏆 Otimização de '{specialist_name}' concluída. Melhor Score: {best_score:.4f}")

                if best_score > settings.optimizer.quality_threshold:
                    logger.info(f"   -> Score excelente! Treinando e salvando modelo final...")
                    
                    # Treina o modelo final com os melhores parâmetros e TODOS os dados disponíveis
                    final_model, final_scaler = self.trainer.train(data, best_params, specialist_features)
                    
                    if final_model and final_scaler:
                        # Salva os artefactos
                        joblib.dump(final_model, os.path.join(situation_models_path, f"model_{specialist_name}.joblib"))
                        joblib.dump(final_scaler, os.path.join(situation_models_path, f"scaler_{specialist_name}.joblib"))
                        
                        # Salva os parâmetros e features usadas
                        artefact_info = {
                            "best_params": best_params,
                            "best_score": best_score,
                            "feature_names": specialist_features,
                            "trained_at": datetime.datetime.now().isoformat()
                        }
                        with open(os.path.join(situation_models_path, f"params_{specialist_name}.json"), 'w') as f:
                            json.dump(artefact_info, f, indent=4)
                        
                        logger.info(f"   -> ✅ Modelo, Scaler e Parâmetros para '{specialist_name}' salvos com sucesso!")

                else:
                    logger.warning(f"   -> Score de {best_score:.4f} não atingiu o limiar de qualidade ({settings.optimizer.quality_threshold}). Modelo não foi salvo.")

            except ValueError:
                logger.warning(f"❌ Nenhum trial concluído com sucesso para o especialista '{specialist_name}'.")

    def run(self) -> None:
        """Executa o processo de otimização completo."""
        logger.info("\n" + "="*80 + "\n--- 🚀 INICIANDO PROCESSO DE OTIMIZAÇÃO DA MENTE-COLMEIA 🚀 ---\n" + "="*80)
        optuna.logging.set_verbosity(optuna.logging.WARNING)

        self.run_optimization_for_situation("all_data", self.full_data)

        logger.info("\n" + "="*80 + "\n--- ✅ PROCESSO DE OTIMIZAÇÃO CONCLUÍDO ✅ ---\n" + "="*80)

# src/core/optimizer.py

# ... (todo o resto do seu código, como a classe WalkForwardOptimizer, continua igual) ...

if __name__ == '__main__':
    import datetime  # Import necessário para a lógica de salvar artefactos

    logger.info("--- 🌐 INICIANDO PIPELINE DE DADOS E FEATURES 🌐 ---")
    
    # --- A MUDANÇA ESTÁ AQUI ---
    # 1. Instanciamos o DataManager
    data_manager = DataManager()
    
    # 2. Executamos o pipeline completo. 
    #    Esta função agora é responsável por verificar, popular (bootstrap), 
    #    atualizar a base de dados e adicionar features.
    df_with_features = data_manager.run_data_pipeline(symbol='BTCUSDT', interval='1m')

    # 3. Verificamos se o pipeline retornou dados válidos antes de continuar
    if df_with_features is not None and not df_with_features.empty:
        logger.info("✅ Pipeline de dados concluído com sucesso. Iniciando o otimizador...")
        optimizer = WalkForwardOptimizer(full_data=df_with_features)
        optimizer.run()
    else:
        logger.error("❌ O pipeline de dados não retornou um DataFrame válido. Otimização abortada.")