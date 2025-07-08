# src/optimizer.py (VERSÃO 5.0 - APRENDIZAGEM ROBUSTA)

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
from src.backtest import run_backtest # A nossa nova função de backtest robusto
from src.logger import logger, log_table
from src.config import (
    WFO_TRAIN_MINUTES, MODEL_VALIDITY_MONTHS, QUICK_OPTIMIZE,
    FEE_RATE, SLIPPAGE_RATE, MODEL_METADATA_FILE, DATA_DIR
)

class WalkForwardOptimizer:
    def __init__(self, full_data):
        self.full_data = full_data
        self.trainer = ModelTrainer()
        self.n_trials_for_cycle = 75 if QUICK_OPTIMIZE else 150 # Aumentado um pouco para os novos params
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
        if trial.number > 0 and trial.number % 5 == 0:
            try:
                best_value = study.best_value
                logger.info(f"  Trials: {trial.number}/{self.n_trials_for_cycle} | Melhor Score: {best_value:.4f}")
            except ValueError:
                logger.info(f"  Trials: {trial.number}/{self.n_trials_for_cycle} | (Aguardando primeiro resultado válido)")

    def _objective(self, trial, train_data, validation_data):
        if self.shutdown_requested:
            raise optuna.exceptions.TrialPruned("Shutdown solicitado.")
        
        # --- MUDANÇA: OTIMIZANDO NOVOS HIPERPARÂMETROS ROBUSTOS ---
        params = {
            # Parâmetros de Labeling e Estratégia
            'future_periods': trial.suggest_int('future_periods', 20, 80),
            'profit_mult': trial.suggest_float('profit_mult', 2.0, 5.0),
            'stop_mult': trial.suggest_float('stop_mult', 1.5, 4.0),
            'profit_threshold': trial.suggest_float('profit_threshold', 0.008, 0.025),
            'stop_loss_atr_multiplier': trial.suggest_float('stop_loss_atr_multiplier', 2.0, 5.0),
            'trailing_stop_multiplier': trial.suggest_float('trailing_stop_multiplier', 1.5, 3.5),
            'risk_per_trade_pct': trial.suggest_float('risk_per_trade_pct', 0.03, 0.20),
            
            # Parâmetros de Agressividade
            'aggression_exponent': trial.suggest_float('aggression_exponent', 1.5, 3.0),
            'max_risk_scale': trial.suggest_float('max_risk_scale', 2.5, 5.0),

            # Parâmetros do Confidence Manager
            'initial_confidence': trial.suggest_float('initial_confidence', 0.60, 0.85),
            'confidence_learning_rate': trial.suggest_float('confidence_learning_rate', 0.02, 0.10),
            'confidence_window_size': trial.suggest_int('confidence_window_size', 5, 20),

            # Parâmetros do Modelo LGBM
            'n_estimators': trial.suggest_int('n_estimators', 150, 400),
            'learning_rate': trial.suggest_float('learning_rate', 0.02, 0.1),
            'num_leaves': trial.suggest_int('num_leaves', 20, 60),
            'max_depth': trial.suggest_int('max_depth', 5, 15),
            'min_child_samples': trial.suggest_int('min_child_samples', 30, 100),
        }
        
        round_trip_cost = (FEE_RATE + SLIPPAGE_RATE) * 2
        if params['profit_threshold'] <= round_trip_cost * 2:
            raise optuna.exceptions.TrialPruned("Alvo de lucro muito baixo comparado aos custos.")

        model, scaler, feature_names = self.trainer.train(train_data.copy(), params)
        if model is None: return -2.0

        # --- NOVO: LÓGICA DE VALIDAÇÃO E OVERFITTING ---
        # 1. Backtest nos dados de VALIDAÇÃO (o teste real)
        val_metrics = run_backtest(
            model=model, scaler=scaler, test_data_with_features=validation_data.copy(), 
            strategy_params=params, feature_names=feature_names
        )
        (_, val_annual_return, _, val_trade_count, val_sortino, val_profit_factor, _) = val_metrics

        # 2. Poda por performance ruim na validação
        MIN_TRADES_SIGNIFICATIVOS = 30
        if val_trade_count < MIN_TRADES_SIGNIFICATIVOS or val_profit_factor < 1.15 or val_annual_return < 0.1:
            raise optuna.exceptions.TrialPruned("Performance na validação abaixo do mínimo aceitável.")

        # 3. Backtest nos dados de TREINO (para checar overfitting)
        train_metrics = run_backtest(
            model=model, scaler=scaler, test_data_with_features=train_data.copy(),
            strategy_params=params, feature_names=feature_names
        )
        (_, _, _, _, train_sortino, train_profit_factor, _) = train_metrics

        # 4. Detecção de Overfitting
        # Se a performance no treino for muito superior à da validação, é um mau sinal.
        if train_sortino > (val_sortino * 2.5) or train_profit_factor > (val_profit_factor * 2.0):
             raise optuna.exceptions.TrialPruned("Overfitting detectado: performance no treino muito superior à validação.")
        
        del model, scaler
        gc.collect()
        
        # --- NOVA FUNÇÃO OBJETIVO COMPOSTA ---
        score_principal = (0.6 * val_sortino) + (0.4 * val_profit_factor)

        # --- NOVA PENALIDADE POR HIPERATIVIDADE ---
        IDEAL_MAX_TRADES = 150
        trade_penalty = 0
        if val_trade_count > IDEAL_MAX_TRADES:
            excess_trades = val_trade_count - IDEAL_MAX_TRADES
            trade_penalty = (score_principal * 0.1) * (excess_trades / IDEAL_MAX_TRADES)
        
        final_score = score_principal - trade_penalty
        
        return final_score if not (math.isnan(final_score) or math.isinf(final_score)) else -1.0

    def run_optimization_for_regime(self, regime: str, regime_data: pd.DataFrame):
        logger.info("\n" + "#"*80 + f"\n# 💠 INICIANDO OTIMIZAÇÃO PARA O REGIME: {regime.upper()} 💠\n" + "#"*80)

        # --- NOVO: ZONA DE QUARENTENA ---
        QUARANTINE_MINUTES = 2880 # 2 dias de dados entre treino e validação
        validation_pct = 0.25
        
        validation_size = int(len(regime_data) * validation_pct)
        train_end_index = len(regime_data) - validation_size
        
        if (train_end_index - QUARANTINE_MINUTES) <= 500: # Checa se o treino ainda tem dados suficientes
            logger.warning(f"Dados insuficientes para o regime '{regime}' após quarentena. Pulando.")
            self.optimization_summary[regime] = {'status': 'Skipped - Insufficient Data', 'score': None}
            return None

        train_data = regime_data.iloc[:(train_end_index - QUARANTINE_MINUTES)]
        validation_data = regime_data.iloc[train_end_index:]
        
        log_table(f"Plano de Otimização para {regime}", [
            ["Período de Treino", f"{train_data.index.min():%Y-%m-%d} a {train_data.index.max():%Y-%m-%d}", f"{len(train_data)} velas"],
            ["Zona de Quarentena", f"({QUARANTINE_MINUTES // 1440} dias)", f"{QUARANTINE_MINUTES} velas"],
            ["Período de Validação", f"{validation_data.index.min():%Y-%m-%d} a {validation_data.index.max():%Y-%m-%d}", f"{len(validation_data)} velas"],
            ["Total de Trials", self.n_trials_for_cycle, ""]
        ], headers=["Fase", "Período", "Tamanho"])
        
        study = optuna.create_study(direction='maximize')
        study.optimize(lambda trial: self._objective(trial, train_data, validation_data), n_trials=self.n_trials_for_cycle, n_jobs=-1, callbacks=[self._progress_callback])
        
        best_trial = study.best_trial
        best_score = best_trial.value if best_trial else -1

        logger.info(f"\n🏁 Otimização do regime '{regime}' concluída. Melhor Score (Composto): {best_score:.4f}")
        
        # --- MUDANÇA --- Limiar de qualidade ajustado para a nova métrica de score
        if best_score > 1.0: # Um bom Sortino/PF combinado deve ser > 1
            logger.info(f"🏆 Resultado excelente! Salvando especialista para o regime '{regime}'...")
            
            # Retreinando o modelo final com todos os dados do regime (treino + validação)
            final_model, final_scaler, final_feature_names = self.trainer.train(regime_data.copy(), best_trial.params)
            
            model_filename = f'trading_model_{regime}.joblib'
            scaler_filename = model_filename.replace('trading_model', 'scaler')
            params_filename = f'strategy_params_{regime}.json'

            joblib.dump(final_model, os.path.join(DATA_DIR, model_filename))
            joblib.dump(final_scaler, os.path.join(DATA_DIR, scaler_filename))

            # Separa os parâmetros do modelo e da estratégia para salvar
            model_param_keys = LGBMClassifier().get_params().keys()
            strategy_params_to_save = {k: v for k, v in best_trial.params.items() if k not in model_param_keys}

            with open(os.path.join(DATA_DIR, params_filename), 'w') as f:
                json.dump(strategy_params_to_save, f, indent=4)
            
            self.optimization_summary[regime] = {
                'status': 'Optimized and Saved', 'score': best_score,
                'model_file': model_filename, 'params_file': params_filename
            }
            log_table(f"Melhores Parâmetros para {regime}", {k: [v] for k, v in best_trial.params.items()}, headers="keys")
            return final_feature_names
        else:
            logger.warning(f"❌ Melhor score ({best_score:.4f}) não atingiu o limiar de qualidade (1.0). Nenhum especialista será salvo para o regime '{regime}'.")
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