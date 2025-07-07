# src/optimizer.py (VERSÃO 4.2 - CORRIGIDO E ROBUSTO)

import optuna
import pandas as pd
import numpy as np
import json
import signal
import os
import math
import gc
import joblib
from datetime import datetime, timezone
from dateutil.relativedelta import relativedelta
from lightgbm import LGBMClassifier

from src.model_trainer import ModelTrainer
from src.backtest import run_backtest
from src.logger import logger, log_table
from src.config import (
    WFO_TRAIN_MINUTES, MODEL_VALIDITY_MONTHS, QUICK_OPTIMIZE,
    FEE_RATE, SLIPPAGE_RATE, MODEL_METADATA_FILE, DATA_DIR
)

class WalkForwardOptimizer:
    def __init__(self, full_data):
        self.full_data = full_data
        self.trainer = ModelTrainer()
        self.n_trials_for_cycle = 50 if QUICK_OPTIMIZE else 100
        self.shutdown_requested = False
        self.optimization_summary = {}
        signal.signal(signal.SIGINT, self.graceful_shutdown)
        signal.signal(signal.SIGTERM, self.graceful_shutdown)

    def graceful_shutdown(self, signum, frame):
        if not self.shutdown_requested:
            logger.warning("\n" + "="*50 + "\n🚨 PARADA SOLICITADA! Finalizando o trial atual...\n" + "="*50)
            self.shutdown_requested = True
    
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
        # CORREÇÃO: Adicionar uma verificação para garantir que best_trial existe
        if trial.number > 0 and trial.number % 5 == 0:
            try:
                # Tenta acessar o melhor trial, mas está preparado para falhar
                best_value = study.best_value
                logger.info(f"  Trials: {trial.number}/{self.n_trials_for_cycle} | Melhor Score: {best_value:.4f}")
            except ValueError:
                # Se nenhum trial foi concluído com sucesso ainda, apenas informa o progresso
                logger.info(f"  Trials: {trial.number}/{self.n_trials_for_cycle} | (Aguardando primeiro resultado válido)")

    def _objective(self, trial, train_data, validation_data):
        if self.shutdown_requested:
            raise optuna.exceptions.TrialPruned("Shutdown solicitado.")
        
        params = {
            'future_periods': trial.suggest_int('future_periods', 15, 90),
            'profit_mult': trial.suggest_float('profit_mult', 2.0, 5.0),
            'stop_mult': trial.suggest_float('stop_mult', 1.5, 4.0),
            'profit_threshold': trial.suggest_float('profit_threshold', 0.005, 0.02),
            'stop_loss_threshold': trial.suggest_float('stop_loss_threshold', 0.003, 0.015),
            'initial_confidence': trial.suggest_float('initial_confidence', 0.60, 0.85),
            'risk_per_trade_pct': trial.suggest_float('risk_per_trade_pct', 0.02, 0.15),
            'confidence_learning_rate': trial.suggest_float('confidence_learning_rate', 0.02, 0.10),
            'confidence_window_size': trial.suggest_int('confidence_window_size', 5, 20),
            'trailing_stop_multiplier': trial.suggest_float('trailing_stop_multiplier', 1.2, 3.0),
            'partial_sell_pct': trial.suggest_float('partial_sell_pct', 0.4, 0.8),
            'treasury_allocation_pct': trial.suggest_float('treasury_allocation_pct', 0.1, 0.5),
            'n_estimators': trial.suggest_int('n_estimators', 150, 400),
            'learning_rate': trial.suggest_float('learning_rate', 0.02, 0.1),
            'num_leaves': trial.suggest_int('num_leaves', 20, 60),
            'max_depth': trial.suggest_int('max_depth', 5, 15),
            'min_child_samples': trial.suggest_int('min_child_samples', 30, 100),
            'feature_fraction': trial.suggest_float('feature_fraction', 0.7, 1.0),
            'bagging_fraction': trial.suggest_float('bagging_fraction', 0.7, 1.0),
        }
        
        round_trip_cost = (FEE_RATE + SLIPPAGE_RATE) * 2
        if params['profit_threshold'] <= params['stop_loss_threshold']:
            raise optuna.exceptions.TrialPruned("Alvo de lucro deve ser maior que o stop loss.")
        if params['profit_threshold'] <= round_trip_cost * 1.5:
            raise optuna.exceptions.TrialPruned("Alvo de lucro muito baixo comparado aos custos.")

        model, scaler, feature_names = self.trainer.train(train_data.copy(), params)
        if model is None: return -2.0

        validation_features, _ = self.trainer._prepare_features(validation_data.copy())
        if validation_features.empty: return -2.0

        _, annualized_return, max_drawdown, trade_count, _ = run_backtest(
            model=model, scaler=scaler, test_data_with_features=validation_features, 
            strategy_params=params, feature_names=feature_names
        )
        
        del model, scaler, validation_features
        gc.collect()
        
        if trade_count < 10: return -1.0
        if annualized_return <= 0: return annualized_return

        calmar_ratio = annualized_return / abs(max_drawdown) if max_drawdown != 0 else 0
        final_score = calmar_ratio * np.log1p(trade_count)
        
        return final_score if not (math.isnan(final_score) or math.isinf(final_score)) else -1.0

    def run_optimization_for_regime(self, regime: str, regime_data: pd.DataFrame):
        logger.info("\n" + "#"*80 + f"\n# 💠 INICIANDO OTIMIZAÇÃO PARA O REGIME: {regime.upper()} 💠\n" + "#"*80)

        validation_pct = 0.25
        validation_size = int(len(regime_data) * validation_pct)
        if len(regime_data) - validation_size <= 200:
            logger.warning(f"Dados insuficientes para o regime '{regime}'. Pulando.")
            self.optimization_summary[regime] = {'status': 'Skipped - Insufficient Data', 'score': None}
            return None

        train_data = regime_data.iloc[:-validation_size]
        validation_data = regime_data.iloc[-validation_size:]
        
        log_table(f"Plano de Otimização para {regime}", [
            ["Período de Treino", f"{train_data.index.min():%Y-%m-%d} a {train_data.index.max():%Y-%m-%d}", f"{len(train_data)} velas"],
            ["Período de Validação", f"{validation_data.index.min():%Y-%m-%d} a {validation_data.index.max():%Y-%m-%d}", f"{len(validation_data)} velas"],
            ["Total de Trials", self.n_trials_for_cycle, ""]
        ], headers=["Fase", "Período", "Tamanho"])
        
        study = optuna.create_study(direction='maximize')
        study.optimize(lambda trial: self._objective(trial, train_data, validation_data), n_trials=self.n_trials_for_cycle, n_jobs=-1, callbacks=[self._progress_callback])
        
        best_trial = study.best_trial
        best_score = best_trial.value if best_trial else -1

        logger.info(f"\n🏁 Otimização do regime '{regime}' concluída. Melhor Score (Calmar ajustado): {best_score:.4f}")
        
        if best_score > 0.5:
            logger.info(f"🏆 Resultado excelente! Salvando especialista para o regime '{regime}'...")
            
            final_model, final_scaler, final_feature_names = self.trainer.train(regime_data.copy(), best_trial.params)
            
            model_filename = f'trading_model_{regime}.joblib'
            scaler_filename = model_filename.replace('trading_model', 'scaler')
            params_filename = f'strategy_params_{regime}.json'

            joblib.dump(final_model, os.path.join(DATA_DIR, model_filename))
            joblib.dump(final_scaler, os.path.join(DATA_DIR, scaler_filename))

            model_param_keys = LGBMClassifier().get_params().keys()
            strategy_params = {k: v for k, v in best_trial.params.items() if k not in model_param_keys}

            with open(os.path.join(DATA_DIR, params_filename), 'w') as f:
                json.dump(strategy_params, f, indent=4)
            
            self.optimization_summary[regime] = {
                'status': 'Optimized and Saved',
                'score': best_score,
                'model_file': model_filename,
                'params_file': params_filename
            }
            log_table(f"Melhores Parâmetros para {regime}", {k: [v] for k, v in best_trial.params.items()}, headers="keys")
            return final_feature_names
        else:
            logger.warning(f"❌ Melhor score na validação ({best_score:.4f}) não atingiu o limiar de qualidade (0.5). Nenhum especialista será salvo para o regime '{regime}'.")
            self.optimization_summary[regime] = {'status': 'Skipped - Low Score', 'score': best_score}
            return None

    def run(self):
        logger.info("\n" + "="*80 + "\n--- 🚀 INICIANDO PROCESSO DE OTIMIZAÇÃO POR ESPECIALISTAS 🚀 ---\n" + "="*80)
        
        optuna.logging.set_verbosity(optuna.logging.WARNING)
        self.full_data.sort_index(inplace=True)
        
        recent_data = self.full_data.tail(WFO_TRAIN_MINUTES)
        regimes = sorted(recent_data['market_regime'].unique())
        
        plan_data = [[regime, len(recent_data[recent_data['market_regime'] == regime])] for regime in regimes]
        log_table("Plano Mestre de Otimização (Dados Recentes)", plan_data, headers=["Regime de Mercado", "Qtd. Velas"])

        master_feature_list = []
        for regime in regimes:
            if self.shutdown_requested:
                logger.warning("Otimização interrompida pelo usuário.")
                break
            
            regime_data = recent_data[recent_data['market_regime'] == regime].copy()
            feature_names = self.run_optimization_for_regime(regime, regime_data)
            if feature_names:
                master_feature_list.extend(feature_names)

        if not self.shutdown_requested:
            unique_features = sorted(list(set(master_feature_list)))
            self._save_final_metadata(unique_features)
        
        final_summary = [[r, d.get('status', 'N/A'), f"{d.get('score', 0):.4f}"] for r, d in self.optimization_summary.items()]
        log_table("📋 RESUMO FINAL DA OTIMIZAÇÃO", final_summary, headers=["Regime", "Status", "Melhor Score"])
        
        logger.info("\n" + "="*80 + "\n--- ✅ PROCESSO DE OTIMIZAÇÃO CONCLUÍDO ✅ ---\n" + "="*80)
