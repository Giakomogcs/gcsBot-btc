# src/optimizer.py (VERSÃO 7.0 - VALIDAÇÃO CRUZADA POR BLOCOS)

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
        # Otimização mais robusta exige mais tempo, então n_trials pode ser ajustado
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
        if trial.number > 0 and trial.number % 2 == 0: # Atualiza com mais frequência
            try:
                best_value = study.best_value
                logger.info(f"  Trials: {trial.number}/{self.n_trials_for_cycle} | Melhor Score (Médio): {best_value:.4f}")
            except ValueError:
                logger.info(f"  Trials: {trial.number}/{self.n_trials_for_cycle} | (Aguardando primeiro resultado válido)")

    def _objective(self, trial, regime_data, regime_blocks):
        if self.shutdown_requested:
            raise optuna.exceptions.TrialPruned("Shutdown solicitado.")
        
        # Parâmetros de otimização (mantidos da sua versão)
        params = {
            'min_risk_scale': trial.suggest_float('min_risk_scale', 0.25, 0.75),
            'future_periods': trial.suggest_int('future_periods', 15, 120),
            'profit_mult': trial.suggest_float('profit_mult', 1.0, 5.0),
            'stop_mult': trial.suggest_float('stop_mult', 1.0, 4.0),
            'profit_threshold': trial.suggest_float('profit_threshold', 0.007, 0.03),
            'stop_loss_atr_multiplier': trial.suggest_float('stop_loss_atr_multiplier', 1.5, 6.0),
            'trailing_stop_multiplier': trial.suggest_float('trailing_stop_multiplier', 1.0, 4.0),
            'risk_per_trade_pct': trial.suggest_float('risk_per_trade_pct', 0.02, 0.30),
            'aggression_exponent': trial.suggest_float('aggression_exponent', 1.0, 3.5),
            'max_risk_scale': trial.suggest_float('max_risk_scale', 2.0, 5.0),
            'initial_confidence': trial.suggest_float('initial_confidence', 0.55, 0.90),
            'confidence_learning_rate': trial.suggest_float('confidence_learning_rate', 0.01, 0.15),
            'confidence_window_size': trial.suggest_int('confidence_window_size', 5, 25),
            'n_estimators': trial.suggest_int('n_estimators', 100, 500),
            'learning_rate': trial.suggest_float('learning_rate', 0.01, 0.15),
            'num_leaves': trial.suggest_int('num_leaves', 20, 70),
            'max_depth': trial.suggest_int('max_depth', 5, 20),
            'min_child_samples': trial.suggest_int('min_child_samples', 20, 100),
        }
        
        round_trip_cost = (FEE_RATE + SLIPPAGE_RATE) * 2
        if params['profit_threshold'] <= round_trip_cost * 1.5:
            raise optuna.exceptions.TrialPruned("Alvo de lucro muito baixo comparado aos custos.")

        # --- LÓGICA DE VALIDAÇÃO CRUZADA POR BLOCOS ---
        all_fold_metrics = []
        for val_block_id in regime_blocks:
            train_block_ids = [b for b in regime_blocks if b != val_block_id]
            
            train_data = regime_data[regime_data['block'].isin(train_block_ids)].copy()
            validation_data = regime_data[regime_data['block'] == val_block_id].copy()

            model, scaler, feature_names = self.trainer.train(train_data, params)
            if model is None:
                raise optuna.exceptions.TrialPruned("Falha no treinamento do modelo em um dos folds.")

            val_metrics = run_backtest(
                model=model, scaler=scaler, test_data_with_features=validation_data, 
                strategy_params=params, feature_names=feature_names
            )
            all_fold_metrics.append(val_metrics)
            del model, scaler
            gc.collect()

        # --- AGREGAÇÃO DOS RESULTADOS DE TODOS OS FOLDS ---
        metrics_df = pd.DataFrame(all_fold_metrics, columns=[
            'final_value', 'annual_return', 'max_dd', 'trade_count', 
            'sortino', 'profit_factor', 'avg_pnl'
        ])

        # Usar mediana para ser mais robusto a um fold com resultado extremo
        median_sortino = metrics_df['sortino'].median()
        median_profit_factor = metrics_df['profit_factor'].median()
        median_annual_return = metrics_df['annual_return'].median()
        total_trade_count = metrics_df['trade_count'].sum()

        MIN_TRADES_POR_FOLD = 5 # Mínimo de trades por bloco de validação
        if (metrics_df['trade_count'] < MIN_TRADES_POR_FOLD).any():
             raise optuna.exceptions.TrialPruned(f"Um dos folds teve menos de {MIN_TRADES_POR_FOLD} trades.")
        
        score_principal = (0.5 * median_sortino) + (0.3 * median_profit_factor) + (0.2 * median_annual_return)
        
        final_score = score_principal
        if math.isnan(final_score) or math.isinf(final_score) or final_score < -1.0:
            raise optuna.exceptions.TrialPruned(f"Score final mediano ({final_score:.4f}) abaixo do limiar de qualidade (0.1).")
            
        return final_score

    def run_optimization_for_regime(self, regime: str, all_recent_data: pd.DataFrame):
        logger.info("\n" + "#"*80 + f"\n# 💠 INICIANDO OTIMIZAÇÃO PARA O REGIME: {regime.upper()} 💠\n" + "#"*80)

        # Identifica os blocos de dados contínuos para o regime atual
        all_recent_data['block'] = (all_recent_data['market_regime'] != all_recent_data['market_regime'].shift()).cumsum()
        regime_data = all_recent_data[all_recent_data['market_regime'] == regime].copy()
        regime_blocks = regime_data['block'].unique()

        if len(regime_blocks) < 2:
            logger.warning(f"❌ Apenas {len(regime_blocks)} bloco(s) de dados encontrado(s) para o regime '{regime}'. É necessário no mínimo 2 para a Validação Cruzada. Pulando.")
            self.optimization_summary[regime] = {'status': 'Skipped - Not Enough Regime Blocks', 'score': None}
            return None

        log_table(f"Plano de Otimização para {regime} (Validação Cruzada)", [
            ["Dados Totais", f"{regime_data.index.min():%Y-%m-%d} a {regime_data.index.max():%Y-%m-%d}", f"{len(regime_data)} velas"],
            ["Blocos Encontrados", f"{len(regime_blocks)} blocos distintos", "Cada bloco será usado como validação"],
            ["Total de Trials", self.n_trials_for_cycle, ""]
        ], headers=["Fase", "Detalhe", "Tamanho"])
        
        study = optuna.create_study(direction='maximize')
        # Passa os dados do regime e a lista de blocos para a função objetivo
        study.optimize(lambda trial: self._objective(trial, regime_data, regime_blocks.tolist()), n_trials=self.n_trials_for_cycle, n_jobs=-1, callbacks=[self._progress_callback])
        
        try:
            best_trial = study.best_trial
            best_score = best_trial.value
        except ValueError:
            logger.warning(f"❌ Nenhum trial concluído com sucesso para o regime '{regime}'. Todos foram podados. Pulando este regime.")
            self.optimization_summary[regime] = {'status': 'Skipped - All Trials Pruned', 'score': None}
            return None
            
        logger.info(f"\n🏁 Otimização do regime '{regime}' concluída. Melhor Score (Médio): {best_score:.4f}")
        
        MINIMUM_QUALITY_SCORE = 0.5 
        if best_score > MINIMUM_QUALITY_SCORE:
            logger.info(f"🏆 Resultado excelente! Score ({best_score:.4f}) acima do limiar ({MINIMUM_QUALITY_SCORE}). Salvando especialista...")
            
            # Retreina com todos os dados do regime para o modelo final
            final_model, final_scaler, final_feature_names = self.trainer.train(regime_data, best_trial.params)
            
            model_filename = f'trading_model_{regime}.joblib'
            scaler_filename = model_filename.replace('trading_model', 'scaler')
            params_filename = f'strategy_params_{regime}.json'

            joblib.dump(final_model, os.path.join(DATA_DIR, model_filename))
            joblib.dump(final_scaler, os.path.join(DATA_DIR, scaler_filename))

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
            logger.warning(f"❌ Melhor score ({best_score:.4f}) não atingiu o limiar de qualidade ({MINIMUM_QUALITY_SCORE}). Nenhum especialista será salvo.")
            self.optimization_summary[regime] = {'status': 'Skipped - Low Score', 'score': best_score}
            return None

    def run(self):
        logger.info("\n" + "="*80 + "\n--- 🚀 INICIANDO PROCESSO DE OTIMIZAÇÃO POR ESPECIALISTAS 🚀 ---\n" + "="*80)
        
        optuna.logging.set_verbosity(optuna.logging.WARNING)
        self.full_data.sort_index(inplace=True)
        
        recent_data = self.full_data.tail(WFO_TRAIN_MINUTES).copy()
        
        regimes = sorted(recent_data['market_regime'].unique())
        
        plan_data = [[regime, len(recent_data[recent_data['market_regime'] == regime])] for regime in regimes]
        log_table("Plano Mestre de Otimização (Dados Recentes)", plan_data, headers=["Regime de Mercado", "Qtd. Velas"])

        master_feature_list = []
        for regime in regimes:
            if self.shutdown_requested:
                logger.warning("Otimização interrompida pelo usuário.")
                break

            # A chamada aqui não precisa mudar, pois a função interna foi ajustada
            feature_names = self.run_optimization_for_regime(regime, recent_data)
            
            if feature_names:
                master_feature_list.extend(feature_names)

        if not self.shutdown_requested:
            unique_features = sorted(list(set(master_feature_list)))
            self._save_final_metadata(unique_features)
        
        final_summary = [[r, d.get('status', 'N/A'), f"{(d.get('score') or 0):.4f}"] for r, d in self.optimization_summary.items()]
        log_table("📋 RESUMO FINAL DA OTIMIZAÇÃO", final_summary, headers=["Regime", "Status", "Melhor Score"])
        
        logger.info("\n" + "="*80 + "\n--- ✅ PROCESSO DE OTIMIZAÇÃO CONCLUÍDO ✅ ---\n" + "="*80)