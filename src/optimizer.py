# src/optimizer.py (VERSÃO 8.6 - Com Contagem Agregada de Podas)

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
from filelock import FileLock
from collections import defaultdict

from src.model_trainer import ModelTrainer
from src.backtest import run_backtest
from src.logger import logger, log_table
from src.config import (
    WFO_TRAIN_MINUTES, MODEL_VALIDITY_MONTHS,
    FEE_RATE, SLIPPAGE_RATE, MODEL_METADATA_FILE, DATA_DIR
)

OPTIMIZER_STATUS_FILE = os.path.join(DATA_DIR, 'optimizer_status.json')
OPTIMIZER_STATUS_LOCK_FILE = os.path.join(DATA_DIR, 'optimizer_status.json.lock')

class WalkForwardOptimizer:
    def __init__(self, full_data, feature_names):
        self.full_data = full_data
        self.feature_names = feature_names
        self.trainer = ModelTrainer()
        self.n_trials_for_cycle = 150
        self.shutdown_requested = False
        self.optimization_summary = {}
        self.current_regime = "N/A"
        self.start_time = time.time()
        signal.signal(signal.SIGINT, self.graceful_shutdown)
        signal.signal(signal.SIGTERM, self.graceful_shutdown)

    def graceful_shutdown(self, signum, frame):
        if not self.shutdown_requested:
            logger.warning("\n" + "="*50 + "\n🚨 PARADA SOLICITADA! Finalizando o trial atual...\n" + "="*50)
            self.shutdown_requested = True
            if os.path.exists(OPTIMIZER_STATUS_FILE): os.remove(OPTIMIZER_STATUS_FILE)

    def _save_final_metadata(self):
        try:
            logger.info("💾 Salvando metadados finais e data de validade do conjunto de modelos...")
            now_utc = datetime.now(timezone.utc)
            valid_until = now_utc + relativedelta(months=MODEL_VALIDITY_MONTHS)

            for regime, result in list(self.optimization_summary.items()):
                if result.get('status') == 'Fallback to Generalist':
                    fallback_model_name = result.get('fallback_model')
                    if fallback_model_name in self.optimization_summary:
                        self.optimization_summary[regime] = self.optimization_summary[fallback_model_name]

            metadata = {
                'last_optimization_date': now_utc.isoformat(),
                'valid_until': valid_until.isoformat(),
                'model_validity_months': MODEL_VALIDITY_MONTHS,
                'feature_names': self.feature_names,
                'optimization_summary': self.optimization_summary
            }
            with open(MODEL_METADATA_FILE, 'w') as f:
                json.dump(metadata, f, indent=4)
            logger.info(f"✅ Metadados salvos. Conjunto de modelos válido até {valid_until.strftime('%Y-%m-%d')}.")
        except Exception as e:
            logger.error(f"❌ Falha ao salvar metadados finais: {e}")

    def _progress_callback(self, study, trial):
        lock = FileLock(OPTIMIZER_STATUS_LOCK_FILE, timeout=10)
        with lock:
            pruning_reason_counts = defaultdict(int)
            pruned_trials = []
            for t in study.trials:
                if t.state == optuna.trial.TrialState.PRUNED:
                    reason = t.user_attrs.get("pruned_reason", "Desconhecido")
                    pruning_reason_counts[reason] += 1
                    pruned_trials.append(t)
            
            pruned_history = [{"number": t.number, "reason": t.user_attrs.get("pruned_reason", "N/A")} for t in pruned_trials]

            status_data = {
                "regime_atual": self.current_regime,
                "n_trials": len(study.trials),
                "total_trials": self.n_trials_for_cycle,
                "start_time": self.start_time,
                "n_complete": len([t for t in study.trials if t.state == optuna.trial.TrialState.COMPLETE]),
                "n_pruned": len(pruned_trials),
                "n_running": len([t for t in study.trials if t.state == optuna.trial.TrialState.RUNNING]),
                "best_trial_data": None,
                "completed_specialists": self.optimization_summary,
                "pruned_trials_history": pruned_history[-5:],
                "pruning_reason_summary": dict(pruning_reason_counts)
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

    def _objective(self, trial, data_for_objective):
        if self.shutdown_requested:
            trial.set_user_attr("pruned_reason", "Shutdown solicitado.")
            raise optuna.exceptions.TrialPruned()

        stop_mult = trial.suggest_float('stop_mult', 2.0, 5.0)
        params = {
            'future_periods': trial.suggest_int('future_periods', 40, 240),
            'profit_mult': trial.suggest_float('profit_mult', stop_mult * 1.3, stop_mult + 6.0),
            'stop_mult': stop_mult,
            'stop_loss_atr_multiplier': trial.suggest_float('stop_loss_atr_multiplier', 1.5, 5.0),
            'trailing_stop_multiplier': trial.suggest_float('trailing_stop_multiplier', 1.0, 4.0),
            'profit_threshold': trial.suggest_float('profit_threshold', 0.01, 0.04),
            'risk_per_trade_pct': trial.suggest_float('risk_per_trade_pct', 0.01, 0.15),
            'aggression_exponent': trial.suggest_float('aggression_exponent', 2.0, 5.0),
            'min_risk_scale': trial.suggest_float('min_risk_scale', 0.2, 0.6),
            'max_risk_scale': trial.suggest_float('max_risk_scale', 3.0, 8.0),
            'initial_confidence': trial.suggest_float('initial_confidence', 0.55, 0.85),
            'confidence_learning_rate': trial.suggest_float('confidence_learning_rate', 0.01, 0.10),
            'confidence_window_size': trial.suggest_int('confidence_window_size', 5, 30),
            'confidence_pnl_clamp': trial.suggest_float('confidence_pnl_clamp', 0.01, 0.05),
            'treasury_allocation_pct': trial.suggest_float('treasury_allocation_pct', 0.05, 0.40),
            'n_estimators': trial.suggest_int('n_estimators', 150, 600),
            'learning_rate': trial.suggest_float('learning_rate', 0.01, 0.1),
            'num_leaves': trial.suggest_int('num_leaves', 20, 80),
            'max_depth': trial.suggest_int('max_depth', 5, 25),
            'min_child_samples': trial.suggest_int('min_child_samples', 20, 100),
        }

        data_for_objective['block'] = (data_for_objective['market_regime'] != data_for_objective['market_regime'].shift()).cumsum()
        regime_blocks = sorted(data_for_objective['block'].unique())
        
        all_fold_metrics = []
        for i in range(1, len(regime_blocks)):
            train_data = data_for_objective[data_for_objective['block'].isin(regime_blocks[:i])].copy()
            validation_data = data_for_objective[data_for_objective['block'] == regime_blocks[i]].copy()
            if len(train_data) < 500 or len(validation_data) < 100:
                continue
            model, scaler = self.trainer.train(train_data, params, self.feature_names)
            if model is None:
                continue
            val_metrics = run_backtest(model, scaler, validation_data, params, self.feature_names)
            all_fold_metrics.append(val_metrics)
            del model, scaler
            gc.collect()

        if not all_fold_metrics:
            trial.set_user_attr("pruned_reason", "Nenhum fold de validação produziu resultados.")
            raise optuna.exceptions.TrialPruned()

        metrics_df = pd.DataFrame(all_fold_metrics, columns=['final_value', 'annual_return', 'max_dd', 'trade_count', 'sortino', 'profit_factor', 'avg_pnl'])
        
        median_sortino = metrics_df['sortino'].median()
        median_profit_factor = metrics_df['profit_factor'].median()
        median_annual_return = metrics_df['annual_return'].median()
        total_trades = int(metrics_df['trade_count'].sum())

        if total_trades < 10:
            trial.set_user_attr("pruned_reason", f"Total de trades ({total_trades}) baixo demais.")
            raise optuna.exceptions.TrialPruned()

        score_principal = (0.5 * median_sortino) + (0.4 * median_profit_factor) + (0.1 * median_annual_return)
        score_principal *= np.log1p(total_trades) / np.log1p(50)

        if math.isnan(score_principal) or score_principal < 0.1:
            trial.set_user_attr("pruned_reason", f"Score final ({score_principal:.4f}) abaixo do limiar.")
            raise optuna.exceptions.TrialPruned()
        
        trial.set_user_attr("total_trades", total_trades)
        trial.set_user_attr("median_sortino", median_sortino)
        trial.set_user_attr("median_profit_factor", median_profit_factor)

        logger.debug(f"Trial {trial.number} concluído. Score: {score_principal:.4f}, Trades: {total_trades}")
        return score_principal

    def run_optimization_for_specialist(self, name: str, data: pd.DataFrame):
        self.current_regime = name
        self.start_time = time.time()
        logger.info(f"\n{'='*20} Iniciando otimização para: {name.upper()} ({len(data)} velas) {'='*20}")

        study = optuna.create_study(direction='maximize')
        study.optimize(lambda trial: self._objective(trial, data), n_trials=self.n_trials_for_cycle, n_jobs=-1, callbacks=[self._progress_callback])

        try:
            best_trial = study.best_trial
            best_score = best_trial.value
        except ValueError:
            logger.warning(f"❌ Nenhum trial concluído com sucesso para '{name}'.")
            self.optimization_summary[name] = {'status': 'Skipped - All Trials Pruned', 'score': None}
            return

        logger.info(f"\n🏁 Otimização de '{name}' concluída. Melhor Score: {best_score:.4f}")

        if best_score > 0.33:
            logger.info(f"🏆 Resultado excelente! Salvando especialista para '{name}'...")
            final_model, final_scaler = self.trainer.train(data, best_trial.params, self.feature_names)
            
            model_filename = f'model_{name}.joblib'
            scaler_filename = f'scaler_{name}.joblib'
            params_filename = f'params_{name}.json'
            
            joblib.dump(final_model, os.path.join(DATA_DIR, model_filename))
            joblib.dump(final_scaler, os.path.join(DATA_DIR, scaler_filename))

            strategy_params = {k: v for k, v in best_trial.params.items() if k not in LGBMClassifier().get_params()}
            with open(os.path.join(DATA_DIR, params_filename), 'w') as f:
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

    def run(self):
        logger.info("\n" + "="*80 + "\n--- 🚀 INICIANDO PROCESSO DE OTIMIZAÇÃO (V8.6) 🚀 ---\n" + "="*80)
        optuna.logging.set_verbosity(optuna.logging.WARNING)

        recent_data = self.full_data.tail(WFO_TRAIN_MINUTES).copy()
        
        regime_groups = defaultdict(list)
        MIN_DATA_FOR_SPECIALIST = 5000

        for r in sorted(recent_data['market_regime'].unique()):
            base_regime = r.split('_')[0]
            regime_groups[base_regime].append(r)

        tasks_to_run = {}
        for base, sub_regimes in regime_groups.items():
            is_single_regime = len(sub_regimes) == 1
            data_for_single_regime = recent_data[recent_data['market_regime'] == sub_regimes[0]] if is_single_regime else pd.DataFrame()
            
            if is_single_regime and len(data_for_single_regime) >= MIN_DATA_FOR_SPECIALIST:
                tasks_to_run[sub_regimes[0]] = data_for_single_regime
            else:
                generalist_name = f"GENERAL_{base}"
                logger.info(f"Dados insuficientes para especialista(s) '{', '.join(sub_regimes)}'. Agrupando em '{generalist_name}'.")
                grouped_data = recent_data[recent_data['market_regime'].isin(sub_regimes)]
                tasks_to_run[generalist_name] = grouped_data
                for r in sub_regimes:
                    self.optimization_summary[r] = {'status': 'Fallback to Generalist', 'fallback_model': generalist_name}
        
        log_table("Plano Mestre de Otimização", [[name, len(data)] for name, data in tasks_to_run.items()], headers=["Especialista a Treinar", "Qtd. Velas"])

        for name, data in tasks_to_run.items():
            if self.shutdown_requested:
                logger.warning("Otimização interrompida.")
                break
            self.run_optimization_for_specialist(name, data)

        if not self.shutdown_requested:
            self._save_final_metadata()
        
        log_table("📋 RESUMO FINAL DA OTIMIZAÇÃO", [[r, d.get('status'), f"{(d.get('score') or 0):.4f}", d.get('fallback_model','N/A')] for r, d in self.optimization_summary.items()], headers=["Regime", "Status", "Score", "Fallback"])
        logger.info("\n" + "="*80 + "\n--- ✅ PROCESSO DE OTIMIZAÇÃO CONCLUÍDO ✅ ---\n" + "="*80)
        
        if os.path.exists(OPTIMIZER_STATUS_FILE):
            os.remove(OPTIMIZER_STATUS_FILE)
        if os.path.exists(OPTIMIZER_STATUS_LOCK_FILE):
            os.remove(OPTIMIZER_STATUS_LOCK_FILE)