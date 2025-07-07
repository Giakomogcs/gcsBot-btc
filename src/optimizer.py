# src/optimizer.py (VERSÃO 4.0 - OTIMIZAÇÃO POR ESPECIALISTAS DE REGIME)

import optuna
import pandas as pd
import numpy as np
import json
import signal
import os
import math
import gc
import joblib
from tabulate import tabulate
from datetime import datetime, timezone
from dateutil.relativedelta import relativedelta

from src.model_trainer import ModelTrainer
from src.backtest import run_backtest
from src.logger import logger
from src.config import (
    WFO_TRAIN_MINUTES, MODEL_VALIDITY_MONTHS, QUICK_OPTIMIZE,
    FEE_RATE, SLIPPAGE_RATE, MODEL_METADATA_FILE, MODEL_FILE
)

def log_table(title, data, headers="keys", tablefmt="heavy_grid"):
    """Função auxiliar para logar tabelas de forma limpa."""
    table = tabulate(data, headers=headers, tablefmt=tablefmt, stralign="right")
    logger.info(f"\n--- {title} ---\n{table}")

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
    
    ### PASSO 1: Metadados agora salvam um resumo completo da otimização ###
    def _save_final_metadata(self):
        try:
            logger.info("💾 Salvando metadados finais e data de validade do conjunto de modelos...")
            now_utc = datetime.now(timezone.utc)
            valid_until = now_utc + relativedelta(months=MODEL_VALIDITY_MONTHS)
            
            metadata = {
                'last_optimization_date': now_utc.isoformat(),
                'valid_until': valid_until.isoformat(),
                'model_validity_months': MODEL_VALIDITY_MONTHS,
                'optimization_summary': self.optimization_summary
            }
            
            with open(MODEL_METADATA_FILE, 'w') as f:
                json.dump(metadata, f, indent=4)
            
            logger.info(f"✅ Metadados salvos. Conjunto de modelos válido até {valid_until.strftime('%Y-%m-%d')}.")
        except Exception as e:
            logger.error(f"❌ Falha ao salvar metadados finais: {e}")

    def _progress_callback(self, study, trial):
        # O log de progresso agora é mais conciso para não poluir
        if trial.number > 0 and trial.number % 5 == 0:
            best_value = study.best_value if study.best_trial else float('nan')
            logger.info(f"  Trials: {trial.number}/{self.n_trials_for_cycle} | Melhor Score: {best_value:.4f}")

    def _objective(self, trial, train_data, validation_data):
        if self.shutdown_requested:
            raise optuna.exceptions.TrialPruned("Shutdown solicitado.")
        
        # O espaço de busca foi refinado para maior robustez
        params = {
            # Parâmetros de Labeling (curto prazo)
            'future_periods': trial.suggest_int('future_periods', 15, 90), # 15 a 90 min
            'profit_mult': trial.suggest_float('profit_mult', 2.0, 5.0),
            'stop_mult': trial.suggest_float('stop_mult', 1.5, 4.0),
            
            # Parâmetros de Estratégia (alvos pequenos, stops curtos)
            'profit_threshold': trial.suggest_float('profit_threshold', 0.005, 0.02), # 0.5% a 2%
            'stop_loss_threshold': trial.suggest_float('stop_loss_threshold', 0.003, 0.015), # 0.3% a 1.5%
            
            # Parâmetros de Gestão de Risco e Confiança
            'initial_confidence': trial.suggest_float('initial_confidence', 0.60, 0.85),
            'risk_per_trade_pct': trial.suggest_float('risk_per_trade_pct', 0.02, 0.15),
            'confidence_learning_rate': trial.suggest_float('confidence_learning_rate', 0.02, 0.10),
            'confidence_window_size': trial.suggest_int('confidence_window_size', 5, 20),
            'trailing_stop_multiplier': trial.suggest_float('trailing_stop_multiplier', 1.2, 3.0),
            'partial_sell_pct': trial.suggest_float('partial_sell_pct', 0.4, 0.8),

            # Parâmetros do Modelo (Regularização mais forte)
            'n_estimators': trial.suggest_int('n_estimators', 150, 400),
            'learning_rate': trial.suggest_float('learning_rate', 0.02, 0.1),
            'num_leaves': trial.suggest_int('num_leaves', 20, 60),
            'max_depth': trial.suggest_int('max_depth', 5, 15),
            'min_child_samples': trial.suggest_int('min_child_samples', 30, 100),
            'feature_fraction': trial.suggest_float('feature_fraction', 0.7, 1.0),
            'bagging_fraction': trial.suggest_float('bagging_fraction', 0.7, 1.0),
        }
        
        ### PASSO 2: Adicionar mais checagens de sanidade para podar trials ruins ###
        # Garante que o alvo de lucro seja maior que os custos + stop loss
        round_trip_cost = (FEE_RATE + SLIPPAGE_RATE) * 2
        if params['profit_threshold'] <= params['stop_loss_threshold']:
            raise optuna.exceptions.TrialPruned("Alvo de lucro deve ser maior que o stop loss.")
        if params['profit_threshold'] <= round_trip_cost * 1.5:
            raise optuna.exceptions.TrialPruned("Alvo de lucro muito baixo comparado aos custos.")

        # Treina o modelo
        model, scaler = self.trainer.train(train_data.copy(), params)
        if model is None: return -2.0

        # Prepara features para validação
        validation_features = self.trainer._prepare_features(validation_data.copy())
        if validation_features.empty: return -2.0

        # Executa o backtest de validação
        final_capital, annualized_return, max_drawdown, trade_count = run_backtest(
            model=model, 
            scaler=scaler, 
            test_data_with_features=validation_features, 
            strategy_params=params, 
            feature_names=self.trainer.final_feature_names
        )
        
        # Limpa a memória
        del model, scaler, validation_features
        gc.collect()
        
        # Lógica de pontuação aprimorada
        if trade_count < 10: return -1.0 # Exige um número mínimo de trades para relevância estatística
        if annualized_return <= 0: return annualized_return # Retorno negativo é a própria pontuação ruim

        calmar_ratio = annualized_return / abs(max_drawdown) if max_drawdown != 0 else 0
        
        # A pontuação final é o Calmar, penalizando levemente a falta de trades
        # Um Calmar alto com poucos trades ainda é melhor que um Calmar baixo com muitos trades
        final_score = calmar_ratio * np.log1p(trade_count)
        
        return final_score if not (math.isnan(final_score) or math.isinf(final_score)) else -1.0

    ### PASSO 3: Lógica de otimização agora salva um especialista completo por regime ###
    def run_optimization_for_regime(self, regime: str, regime_data: pd.DataFrame):
        logger.info("\n" + "#"*80 + f"\n# 💠 INICIANDO OTIMIZAÇÃO PARA O REGIME: {regime.upper()} 💠\n" + "#"*80)

        # Divisão treino/validação
        validation_pct = 0.25
        validation_size = int(len(regime_data) * validation_pct)
        if len(regime_data) - validation_size <= 200: # Garante dados de treino suficientes
            logger.warning(f"Dados insuficientes para o regime '{regime}'. Pulando.")
            self.optimization_summary[regime] = {'status': 'Skipped - Insufficient Data', 'score': None}
            return

        train_data = regime_data.iloc[:-validation_size]
        validation_data = regime_data.iloc[-validation_size:]
        
        log_table(f"Plano de Otimização para {regime}", [
            ["Período de Treino", f"{train_data.index.min():%Y-%m-%d} a {train_data.index.max():%Y-%m-%d}", f"{len(train_data)} velas"],
            ["Período de Validação", f"{validation_data.index.min():%Y-%m-%d} a {validation_data.index.max():%Y-%m-%d}", f"{len(validation_data)} velas"],
            ["Total de Trials", self.n_trials_for_cycle, ""]
        ], headers=["Fase", "Período", "Tamanho"])
        
        # Executa o estudo do Optuna
        study = optuna.create_study(direction='maximize')
        study.optimize(lambda trial: self._objective(trial, train_data, validation_data), n_trials=self.n_trials_for_cycle, n_jobs=-1, callbacks=[self._progress_callback])
        
        # Processa os resultados
        best_trial = study.best_trial
        best_score = best_trial.value if best_trial else -1

        logger.info(f"\n🏁 Otimização do regime '{regime}' concluída. Melhor Score (Calmar ajustado): {best_score:.4f}")
        
        if best_score > 0.5: # Limiar de qualidade para salvar o especialista
            logger.info(f"🏆 Resultado excelente! Salvando especialista para o regime '{regime}'...")
            
            # Re-treina o modelo com os melhores parâmetros usando TODOS os dados do regime
            final_model, final_scaler = self.trainer.train(regime_data.copy(), best_trial.params)
            
            # Salva o modelo e o scaler específicos do regime
            model_path = MODEL_FILE.replace('.joblib', f'_{regime}.joblib')
            scaler_path = model_path.replace('trading_model', 'scaler')
            joblib.dump(final_model, model_path)
            joblib.dump(final_scaler, scaler_path)

            # Salva os parâmetros de estratégia do regime
            strategy_params = {k: v for k, v in best_trial.params.items() if k not in self.trainer.base_feature_names}
            params_path = MODEL_METADATA_FILE.replace('model_metadata.json', f'strategy_params_{regime}.json')
            with open(params_path, 'w') as f:
                json.dump(strategy_params, f, indent=4)
            
            # Atualiza o resumo da otimização
            self.optimization_summary[regime] = {
                'status': 'Optimized and Saved',
                'score': best_score,
                'model_file': os.path.basename(model_path),
                'params_file': os.path.basename(params_path)
            }
            log_table(f"Melhores Parâmetros para {regime}", {k: [v] for k, v in best_trial.params.items()}, headers="keys")
        else:
            logger.warning(f"❌ Melhor score na validação ({best_score:.4f}) não atingiu o limiar de qualidade (0.5). Nenhum especialista será salvo para o regime '{regime}'.")
            self.optimization_summary[regime] = {'status': 'Skipped - Low Score', 'score': best_score}

    def run(self):
        """Orquestrador principal que otimiza um modelo especialista para cada regime de mercado."""
        logger.info("\n" + "="*80 + "\n--- 🚀 INICIANDO PROCESSO DE OTIMIZAÇÃO POR ESPECIALISTAS 🚀 ---\n" + "="*80)
        
        optuna.logging.set_verbosity(optuna.logging.WARNING)
        self.full_data.sort_index(inplace=True)
        
        recent_data = self.full_data.tail(WFO_TRAIN_MINUTES)
        regimes = sorted(recent_data['market_regime'].unique())
        
        plan_data = [[regime, len(recent_data[recent_data['market_regime'] == regime])] for regime in regimes]
        log_table("Plano Mestre de Otimização (Dados Recentes)", plan_data, headers=["Regime de Mercado", "Qtd. Velas"])

        for regime in regimes:
            if self.shutdown_requested:
                logger.warning("Otimização interrompida pelo usuário.")
                break
            
            regime_data = recent_data[recent_data['market_regime'] == regime].copy()
            self.run_optimization_for_regime(regime, regime_data)

        # Salva os metadados finais com o resumo
        self._save_final_metadata()
        
        final_summary = [[r, d.get('status', 'N/A'), f"{d.get('score', 0):.4f}"] for r, d in self.optimization_summary.items()]
        log_table("📋 RESUMO FINAL DA OTIMIZAÇÃO", final_summary, headers=["Regime", "Status", "Melhor Score"])
        
        logger.info("\n" + "="*80 + "\n--- ✅ PROCESSO DE OTIMIZAÇÃO CONCLUÍDO ✅ ---\n" + "="*80)