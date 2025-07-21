# src/optimizer.py (VERSÃO 9.0 - FÁBRICA DE ESPECIALISTAS COMPLETA)

import optuna
import pandas as pd
import numpy as np
import json
import signal
import os
import math
import gc
import joblib
import sys
import time
from datetime import datetime, timezone
from dateutil.relativedelta import relativedelta
from lightgbm import LGBMClassifier
import lightgbm as lgb
from filelock import FileLock
from collections import defaultdict

from src.core.model_trainer import ModelTrainer
from src.core.backtest import BacktestingEngine
from src.logger import logger, log_table
from src.config import settings

OPTIMIZER_STATUS_FILE = os.path.join(settings.DATA_DIR, 'optimizer_status.json')
OPTIMIZER_STATUS_LOCK_FILE = os.path.join(settings.DATA_DIR, 'optimizer_status.json.lock')

from typing import List, Dict, Any

class WalkForwardOptimizer:
    """A class to perform walk-forward optimization."""

    def __init__(self, full_data: pd.DataFrame, feature_names: List[str]) -> None:
        """
        Initializes the WalkForwardOptimizer class.

        Args:
            full_data: The full dataset.
            feature_names: The names of the features to use.
        """
        self.full_data = full_data
        self.feature_names = feature_names
        self.trainer = ModelTrainer()
        self.n_trials_for_cycle = 150
        self.shutdown_requested = False
        self.optimization_summary = {}
        self.current_regime = "N/A"
        self.start_time = time.time()
        self.cumulative_pruning_stats = defaultdict(int)
        signal.signal(signal.SIGINT, self.graceful_shutdown)
        signal.signal(signal.SIGTERM, self.graceful_shutdown)

    def graceful_shutdown(self, signum: int, frame: Any) -> None:
        """Gracefully shuts down the optimizer."""
        if not self.shutdown_requested:
            logger.warning("\n" + "="*50 + "\n🚨 PARADA SOLICITADA! Finalizando o trial atual...\n" + "="*50)
            self.shutdown_requested = True
            if os.path.exists(OPTIMIZER_STATUS_FILE): os.remove(OPTIMIZER_STATUS_FILE)

    def _save_final_metadata(self) -> None:
        """Saves the final metadata."""
        try:
            logger.info("💾 Salvando metadados finais e data de validade do conjunto de modelos...")
            now_utc = datetime.now(timezone.utc)
            valid_until = now_utc + relativedelta(months=settings.MODEL_VALIDITY_MONTHS)

            metadata = {
                'last_optimization_date': now_utc.isoformat(),
                'valid_until': valid_until.isoformat(),
                'model_validity_months': settings.MODEL_VALIDITY_MONTHS,
                'feature_names': self.feature_names,
                'optimization_summary': self.optimization_summary
            }
            with open(settings.MODEL_METADATA_FILE, 'w') as f:
                json.dump(metadata, f, indent=4)
            logger.info(f"✅ Metadados salvos. Conjunto de modelos válido até {valid_until.strftime('%Y-%m-%d')}.")
        except Exception as e:
            logger.error(f"❌ Falha ao salvar metadados finais: {e}")

    def _progress_callback(self, study: optuna.study.Study, trial: optuna.trial.Trial) -> None:
        """
        A callback function to report the progress of the optimization.

        Args:
            study: The study object.
            trial: The trial object.
        """
        lock = FileLock(OPTIMIZER_STATUS_LOCK_FILE, timeout=10)
        with lock:
            current_pruning_counts = defaultdict(int)
            pruned_trials_current_study = []
            for t in study.trials:
                if t.state == optuna.trial.TrialState.PRUNED:
                    reason = t.user_attrs.get("pruned_reason", "Desconhecido")
                    current_pruning_counts[reason] += 1
                    pruned_trials_current_study.append(t)
            
            total_pruning_counts = self.cumulative_pruning_stats.copy()
            for reason, count in current_pruning_counts.items():
                total_pruning_counts[reason] += count

            pruned_history = [{"number": t.number, "reason": t.user_attrs.get("pruned_reason", "N/A")} for t in pruned_trials_current_study]

            status_data = {
                "situation_atual": self.current_regime, "n_trials": len(study.trials),
                "total_trials": self.n_trials_for_cycle, "start_time": self.start_time,
                "n_complete": len([t for t in study.trials if t.state == optuna.trial.TrialState.COMPLETE]),
                "n_pruned": len(pruned_trials_current_study),
                "n_running": len([t for t in study.trials if t.state == optuna.trial.TrialState.RUNNING]),
                "best_trial_data": None,
                "completed_situations": self.optimization_summary,
                "pruned_trials_history": pruned_history[-5:],
                "pruning_reason_summary": dict(total_pruning_counts)
            }
            try:
                best_trial = study.best_trial
                status_data["best_trial_data"] = {
                    "value": best_trial.value,
                    "params": {k: v for k, v in best_trial.params.items() if 'child' not in k},
                    "user_attrs": best_trial.user_attrs
                }
            except ValueError:
                pass
            try:
                with open(OPTIMIZER_STATUS_FILE, 'w') as f:
                    json.dump(status_data, f)
            except Exception as e:
                logger.warning(f"Não foi possível escrever o arquivo de status: {e}")

        if trial.number > 0 and trial.number % 10 == 0:
            try:
                logger.info(f"Progresso: Trial {trial.number}/{self.n_trials_for_cycle}, Melhor Score: {study.best_value:.4f}")
            except ValueError:
                logger.info(f"Progresso: Trial {trial.number}/{self.n_trials_for_cycle}, Aguardando resultado válido...")

    def _objective(self, trial: optuna.trial.Trial, data_for_objective: pd.DataFrame) -> float:
        """
        The objective function to be optimized.

        Args:
            trial: The trial object.
            data_for_objective: The data to use for the objective function.

        Returns:
            The score of the objective function.
        """
        if self.shutdown_requested:
            trial.set_user_attr("pruned_reason", "Shutdown solicitado.")
            raise optuna.exceptions.TrialPruned()

        params = {
            'objective': 'binary',
            'metric': 'binary_logloss',
            'verbosity': -1,
            'boosting_type': 'gbdt',
        }
        
        data_for_objective['block'] = (data_for_objective['market_regime'] != data_for_objective['market_regime'].shift()).cumsum()
        regime_blocks = sorted(data_for_objective['block'].unique())
        
        all_fold_metrics = []
        for i in range(1, len(regime_blocks)):
            train_data = data_for_objective[data_for_objective['block'].isin(regime_blocks[:i])].copy()
            validation_data = data_for_objective[data_for_objective['block'] == regime_blocks[i]].copy()
            if len(train_data) < 500 or len(validation_data) < 100:
                continue
            model, scaler = self.trainer.train(train_data, params, self.feature_names, base_model=self.base_model)
            if model is None:
                continue
            backtesting_engine = BacktestingEngine(model, scaler, validation_data, params, self.feature_names)
            val_metrics = backtesting_engine.run()
            all_fold_metrics.append(val_metrics)
            del model, scaler
            gc.collect()

        if not all_fold_metrics:
            trial.set_user_attr("pruned_reason", "Nenhum fold de validação produziu resultados.")
            raise optuna.exceptions.TrialPruned()

        metrics_df = pd.DataFrame(all_fold_metrics, columns=['final_value', 'annual_return', 'max_dd', 'trade_count', 'sortino', 'profit_factor', 'avg_pnl'])
        
        median_sortino = metrics_df['sortino'].median()
        median_profit_factor = metrics_df['profit_factor'].median()
        total_trades = int(metrics_df['trade_count'].sum())

        if total_trades < 10:
            trial.set_user_attr("pruned_reason", f"Total de trades ({total_trades}) baixo demais.")
            raise optuna.exceptions.TrialPruned()

        if median_profit_factor <= 1 or median_sortino <= 0:
            score_principal = 0.0
        else:
            score_principal = (median_profit_factor - 1) * 10
            score_principal += median_sortino * 0.5 
        
        score_principal *= np.log1p(total_trades) / np.log1p(25)

        if math.isnan(score_principal) or score_principal < 0.01:
            trial.set_user_attr("pruned_reason", f"Score final ({score_principal:.4f}) abaixo do limiar.")
            raise optuna.exceptions.TrialPruned()
        
        trial.set_user_attr("total_trades", total_trades)
        trial.set_user_attr("median_sortino", median_sortino)
        trial.set_user_attr("median_profit_factor", median_profit_factor)

        logger.debug(f"Trial {trial.number} concluído. Score: {score_principal:.4f}, Trades: {total_trades}")
        return score_principal

    def run_optimization_for_situation(self, name: str, data: pd.DataFrame) -> None:
        """
        Runs the optimization for a given situation.

        Args:
            name: The name of the situation.
            data: The data for the situation.
        """
        self.current_regime = name
        self.start_time = time.time()
        logger.info(f"\n{'='*20} Iniciando otimização para: {name.upper()} ({len(data)} velas) {'='*20}")

        tuner = optuna.integration.LightGBMTuner(
            self._objective,
            study_name=name,
            n_trials=self.n_trials_for_cycle,
            n_jobs=-1,
            callbacks=[self._progress_callback],
            model_dir=f"data/models/{name}",
        )
        tuner.run()
        
        for t in tuner.study.get_trials(deepcopy=False, states=[optuna.trial.TrialState.PRUNED]):
            reason = t.user_attrs.get("pruned_reason", "Desconhecido")
            self.cumulative_pruning_stats[reason] += 1

        try:
            best_trial = tuner.study.best_trial
            best_score = best_trial.value
        except ValueError:
            logger.warning(f"❌ Nenhum trial concluído com sucesso para '{name}'.")
            self.optimization_summary[name] = {'status': 'Skipped - All Trials Pruned', 'score': None}
            return

        best_trial = tuner.study.best_trial
        best_score = best_trial.value

        logger.info(f"\n🏁 Otimização de '{name}' concluída. Melhor Score: {best_score:.4f}")

        # Limiar de qualidade para salvar o modelo
        if best_score > 0.33:
            logger.info(f"🏆 Resultado excelente! Salvando especialista para '{name}'...")
            final_model, final_scaler = self.trainer.train(data, best_trial.params, self.feature_names, base_model=self.base_model)
            
            model_filename = f'model_{name}.joblib'
            scaler_filename = f'scaler_{name}.joblib'
            params_filename = f'params_{name}.json'
            
            joblib.dump(final_model, os.path.join(settings.DATA_DIR, model_filename))
            joblib.dump(final_scaler, os.path.join(settings.DATA_DIR, scaler_filename))

            # Separa os parâmetros do modelo e da estratégia para salvar no JSON
            model_keys = LGBMClassifier().get_params().keys()
            strategy_params = {k: v for k, v in best_trial.params.items() if k not in model_keys}
            
            with open(os.path.join(settings.DATA_DIR, params_filename), 'w') as f:
                json.dump(strategy_params, f, indent=4)

            self.optimization_summary[name] = {
                'status': 'Optimized and Saved', 
                'score': best_score, 
                'model_file': model_filename, 
                'params_file': params_filename, 
                'scaler_file': scaler_filename
            }
            log_table(f"Melhores Parâmetros para {name}", {k: [v] for k, v in best_trial.params.items()}, headers="keys")
        else:
            logger.warning(f"❌ Score de '{name}' ({best_score:.4f}) não atingiu o limiar de qualidade (0.33).")
            self.optimization_summary[name] = {'status': 'Skipped - Low Score', 'score': best_score}

    def run(self) -> None:
        """Runs the walk-forward optimization."""
        logger.info("\n" + "="*80 + "\n--- 🚀 INICIANDO PROCESSO DE OTIMIZAÇÃO (V9.0) 🚀 ---\n" + "="*80)
        optuna.logging.set_verbosity(optuna.logging.WARNING)

        base_model_params = {
            'n_estimators': 500,
            'learning_rate': 0.05,
            'num_leaves': 50,
            'max_depth': 15,
            'min_child_samples': 50,
        }
        self.base_model = self.trainer.train_base_model(self.full_data, base_model_params, self.feature_names)

        recent_data = self.full_data.tail(settings.WFO_TRAIN_MINUTES).copy()
        
        situation_groups = recent_data.groupby('market_situation')
        
        tasks_to_run = {}
        for situation, data in situation_groups:
            if len(data) >= 5000:
                tasks_to_run[f"SITUATION_{situation}"] = data
            else:
                logger.info(f"Dados insuficientes para a situação {situation}. Pulando.")

        log_table("Plano Mestre de Otimização", [[name, len(data)] for name, data in tasks_to_run.items()], headers=["Situação a Treinar", "Qtd. Velas"])

        for name, data in tasks_to_run.items():
            if self.shutdown_requested:
                logger.warning("Otimização interrompida.")
                break
            self.run_optimization_for_situation(name, data)

        if not self.shutdown_requested:
            self._save_final_metadata()
        
        log_table("📋 RESUMO FINAL DA OTIMIZAÇÃO", [[r, d.get('status'), f"{(d.get('score') or 0):.4f}", d.get('fallback_model','N/A')] for r, d in self.optimization_summary.items()], headers=["Regime", "Status", "Score", "Fallback"])
        logger.info("\n" + "="*80 + "\n--- ✅ PROCESSO DE OTIMIZAÇÃO CONCLUÍDO ✅ ---\n" + "="*80)
        
        if os.path.exists(OPTIMIZER_STATUS_FILE):
            os.remove(OPTIMIZER_STATUS_FILE)
        if os.path.exists(OPTIMIZER_STATUS_LOCK_FILE):
            os.remove(OPTIMIZER_STATUS_LOCK_FILE)