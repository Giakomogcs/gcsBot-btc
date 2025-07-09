# src/optimizer.py (VERSÃO 7.6 - Otimização Calibrada)

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
    def __init__(self, full_data):
        self.full_data = full_data
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
            if os.path.exists(OPTIMIZER_STATUS_FILE):
                os.remove(OPTIMIZER_STATUS_FILE)

    def _save_final_metadata(self, final_feature_names):
        try:
            logger.info("💾 Salvando metadados finais e data de validade do conjunto de modelos...")
            now_utc = datetime.now(timezone.utc)
            valid_until = now_utc + relativedelta(months=MODEL_VALIDITY_MONTHS)

            metadata = {
                'last_optimization_date': now_utc.isoformat(),
                'valid_until': valid_until.isoformat(),
                'model_validity_months': MODEL_VALIDITY_MONTHS,
                'feature_names': final_feature_names,
                'optimization_summary': self.optimization_summary
            }

            with open(MODEL_METADATA_FILE, 'w') as f:
                json.dump(metadata, f, indent=4)

            logger.info(f"✅ Metadados salvos. Conjunto de modelos válido até {valid_until.strftime('%Y-%m-%d')}.")
        except Exception as e:
            logger.error(f"❌ Falha ao salvar metadados finais: {e}")

    def _progress_callback(self, study, trial):
        """Escreve o status da otimização de forma segura para processos paralelos."""
        lock = FileLock(OPTIMIZER_STATUS_LOCK_FILE, timeout=10)
        with lock:
            n_trials_completed = len(study.trials)
            n_complete = len([t for t in study.trials if t.state == optuna.trial.TrialState.COMPLETE])
            n_pruned = len([t for t in study.trials if t.state == optuna.trial.TrialState.PRUNED])
            n_running = len([t for t in study.trials if t.state == optuna.trial.TrialState.RUNNING])

            status_data = {
                "regime_atual": self.current_regime, "n_trials": n_trials_completed,
                "total_trials": self.n_trials_for_cycle, "start_time": self.start_time,
                "n_complete": n_complete, "n_pruned": n_pruned, "n_running": n_running,
                "best_value": None, "best_params": None,
            }

            try:
                best_trial = study.best_trial
                status_data["best_value"] = best_trial.value
                status_data["best_params"] = {k: v for k, v in best_trial.params.items() if 'child' not in k and 'depth' not in k}
            except ValueError:
                pass

            try:
                with open(OPTIMIZER_STATUS_FILE, 'w') as f:
                    json.dump(status_data, f)
            except Exception as e:
                logger.warning(f"Não foi possível escrever o arquivo de status: {e}")

        if trial.number > 0 and trial.number % 10 == 0:
            try:
                best_value = study.best_value
                logger.info(f"Progresso: Trial {trial.number}/{self.n_trials_for_cycle}, Melhor Score: {best_value:.4f}")
            except ValueError:
                logger.info(f"Progresso: Trial {trial.number}/{self.n_trials_for_cycle}, Aguardando resultado válido...")

    def _objective(self, trial, regime_data, regime_blocks):
        if self.shutdown_requested:
            raise optuna.exceptions.TrialPruned("Shutdown solicitado.")

        stop_mult = trial.suggest_float('stop_mult', 2.0, 5.0)
        min_profit_mult = stop_mult * 1.3
        profit_mult = trial.suggest_float('profit_mult', min_profit_mult, min_profit_mult + 6.0)

        params = {
            'future_periods': trial.suggest_int('future_periods', 40, 240),
            'profit_mult': profit_mult, 'stop_mult': stop_mult,
            'stop_loss_atr_multiplier': trial.suggest_float('stop_loss_atr_multiplier', 1.5, 5.0),
            'trailing_stop_multiplier': trial.suggest_float('trailing_stop_multiplier', 1.0, 4.0),
            'profit_threshold': trial.suggest_float('profit_threshold', 0.01, 0.04),
            'risk_per_trade_pct': trial.suggest_float('risk_per_trade_pct', 0.01, 0.15),
            'aggression_exponent': trial.suggest_float('aggression_exponent', 2.0, 5.0),
            'min_risk_scale': trial.suggest_float('min_risk_scale', 0.2, 0.6),
            'max_risk_scale': trial.suggest_float('max_risk_scale', 3.0, 8.0),
            # <<< ALTERADO 3 >>> Permite testar confianças iniciais um pouco mais baixas.
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

        round_trip_cost = (FEE_RATE + SLIPPAGE_RATE) * 2
        if params['profit_threshold'] <= round_trip_cost * 1.5:
            raise optuna.exceptions.TrialPruned("Alvo de lucro muito baixo comparado aos custos.")

        all_fold_metrics = []
        for val_block_id in regime_blocks:
            train_block_ids = [b for b in regime_blocks if b != val_block_id]
            train_data = regime_data[regime_data['block'].isin(train_block_ids)].copy()
            validation_data = regime_data[regime_data['block'] == val_block_id].copy()

            if len(train_data) < 500 or len(validation_data) < 100: continue

            model, scaler, feature_names = self.trainer.train(train_data, params)
            if model is None: raise optuna.exceptions.TrialPruned("Falha no treinamento do modelo.")

            val_metrics = run_backtest(model=model, scaler=scaler, test_data_with_features=validation_data, strategy_params=params, feature_names=feature_names)
            all_fold_metrics.append(val_metrics)
            del model, scaler; gc.collect()

        if not all_fold_metrics: raise optuna.exceptions.TrialPruned("Nenhum fold de validação produziu resultados.")

        metrics_df = pd.DataFrame(all_fold_metrics, columns=['final_value', 'annual_return', 'max_dd', 'trade_count', 'sortino', 'profit_factor', 'avg_pnl'])
        median_sortino = metrics_df['sortino'].median()
        median_profit_factor = metrics_df['profit_factor'].median()
        median_annual_return = metrics_df['annual_return'].median()

        if (metrics_df['trade_count'] < 2).any():
             raise optuna.exceptions.TrialPruned(f"Um dos folds teve menos de 2 trades.")

        score_principal = (0.5 * median_sortino) + (0.4 * median_profit_factor) + (0.1 * median_annual_return)
        score_principal *= np.log1p(metrics_df['trade_count'].sum()) / 5.0

        if math.isnan(score_principal) or math.isinf(score_principal) or score_principal < 0.1:
            raise optuna.exceptions.TrialPruned(f"Score final ({score_principal:.4f}) abaixo do limiar de qualidade.")

        return score_principal

    def run_optimization_for_regime(self, regime: str, all_recent_data: pd.DataFrame):
        self.current_regime = regime
        self.start_time = time.time()

        logger.info(f"\nIniciando otimização para o regime: {regime.upper()}. Acompanhe em 'run.py display'.")

        all_recent_data['block'] = (all_recent_data['market_regime'] != all_recent_data['market_regime'].shift()).cumsum()
        regime_data = all_recent_data[all_recent_data['market_regime'] == regime].copy()

        block_counts = regime_data['block'].value_counts()
        valid_blocks = block_counts[block_counts > 500].index.tolist()
        regime_blocks = sorted(valid_blocks)

        if len(regime_blocks) < 3:
            logger.warning(f"❌ Apenas {len(regime_blocks)} blocos válidos para '{regime}'. Mínimo de 3. Pulando.")
            self.optimization_summary[regime] = {'status': 'Skipped - Not Enough Blocks', 'score': None}
            return None

        study = optuna.create_study(direction='maximize')
        study.optimize(lambda trial: self._objective(trial, regime_data, regime_blocks), n_trials=self.n_trials_for_cycle, n_jobs=-1, callbacks=[self._progress_callback])

        try:
            best_trial = study.best_trial
            best_score = best_trial.value
        except ValueError:
            logger.warning(f"❌ Nenhum trial concluído com sucesso para o regime '{regime}'.")
            self.optimization_summary[regime] = {'status': 'Skipped - All Trials Pruned', 'score': None}
            return None

        logger.info(f"\n🏁 Otimização do regime '{regime}' concluída. Melhor Score (Médio): {best_score:.4f}")

        if best_score > 0.5:
            logger.info(f"🏆 Resultado excelente! Score ({best_score:.4f}) > 0.5. Salvando especialista...")
            final_model, final_scaler, final_feature_names = self.trainer.train(regime_data, best_trial.params)
            model_filename = f'trading_model_{regime}.joblib'
            params_filename = f'strategy_params_{regime}.json'
            joblib.dump(final_model, os.path.join(DATA_DIR, model_filename))
            joblib.dump(final_scaler, os.path.join(DATA_DIR, model_filename.replace('trading_model', 'scaler')))

            strategy_params_to_save = {k: v for k, v in best_trial.params.items() if k not in LGBMClassifier().get_params().keys()}
            with open(os.path.join(DATA_DIR, params_filename), 'w') as f:
                json.dump(strategy_params_to_save, f, indent=4)

            self.optimization_summary[regime] = {'status': 'Optimized', 'score': best_score, 'model_file': model_filename}
            log_table(f"Melhores Parâmetros para {regime}", {k: [v] for k, v in best_trial.params.items()}, headers="keys")
            return final_feature_names
        else:
            logger.warning(f"❌ Melhor score ({best_score:.4f}) não atingiu o limiar de qualidade (0.5).")
            self.optimization_summary[regime] = {'status': 'Skipped - Low Score', 'score': best_score}
            return None

    def run(self):
        logger.info("\n" + "="*80 + "\n--- 🚀 INICIANDO PROCESSO DE OTIMIZAÇÃO POR ESPECIALISTAS 🚀 ---\n" + "="*80)
        optuna.logging.set_verbosity(optuna.logging.WARNING)

        try:
            initial_status = {
                "regime_atual": "Inicializando...",
                "n_trials": 0, "total_trials": self.n_trials_for_cycle,
                "start_time": time.time(),
                "n_complete": 0, "n_pruned": 0, "n_running": 0,
                "best_value": None, "best_params": None,
            }
            with open(OPTIMIZER_STATUS_FILE, 'w') as f:
                json.dump(initial_status, f)

            self.full_data.sort_index(inplace=True)
            recent_data = self.full_data.tail(WFO_TRAIN_MINUTES).copy()
            regimes = sorted(recent_data['market_regime'].unique())
            
            log_table("Plano Mestre de Otimização (Dados Recentes)", [[regime, len(recent_data[recent_data['market_regime'] == regime])] for regime in regimes], headers=["Regime de Mercado", "Qtd. Velas"])

            master_feature_list = []
            for regime in regimes:
                if self.shutdown_requested:
                    logger.warning("Otimização interrompida.")
                    break
                feature_names = self.run_optimization_for_regime(regime, recent_data)
                if feature_names:
                    master_feature_list.extend(feature_names)

            if not self.shutdown_requested:
                unique_features = sorted(list(set(master_feature_list)))
                if not unique_features:
                     logger.warning("Nenhum especialista foi salvo. Usando features base.")
                     unique_features = self.trainer.base_feature_names
                self._save_final_metadata(unique_features)
            
            log_table("📋 RESUMO FINAL DA OTIMIZAÇÃO", [[r, d.get('status', 'N/A'), f"{(d.get('score') or 0):.4f}"] for r, d in self.optimization_summary.items()], headers=["Regime", "Status", "Melhor Score"])
            logger.info("\n" + "="*80 + "\n--- ✅ PROCESSO DE OTIMIZAÇÃO CONCLUÍDO ✅ ---\n" + "="*80)
        
        finally:
            if os.path.exists(OPTIMIZER_STATUS_FILE):
                os.remove(OPTIMIZER_STATUS_FILE)
            if os.path.exists(OPTIMIZER_STATUS_LOCK_FILE):
                os.remove(OPTIMIZER_STATUS_LOCK_FILE)