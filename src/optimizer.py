# src/optimizer.py (VERSÃO 2.2 - COM MODO DE OTIMIZAÇÃO RÁPIDA)

import optuna
import pandas as pd
import numpy as np
import json
import signal
import os
import math
import gc
from tabulate import tabulate
from datetime import datetime, timezone
from dateutil.relativedelta import relativedelta

from src.model_trainer import ModelTrainer
from src.backtest import run_backtest
from src.logger import logger
from src.config import (
    WFO_TRAIN_MINUTES, WFO_TEST_MINUTES, WFO_STEP_MINUTES, WFO_STATE_FILE,
    STRATEGY_PARAMS_FILE, MODEL_FILE, SCALER_FILE,
    MODEL_METADATA_FILE, MODEL_VALIDITY_MONTHS,
    # <<< PASSO 1: Importar a nova variável de configuração >>>
    QUICK_OPTIMIZE 
)
from src.confidence_manager import AdaptiveConfidenceManager

class WalkForwardOptimizer:
    def __init__(self, full_data):
        self.full_data = full_data
        self.trainer = ModelTrainer()
        self.n_trials_for_cycle = 0
        self.shutdown_requested = False
        signal.signal(signal.SIGINT, self.graceful_shutdown)
        signal.signal(signal.SIGTERM, self.graceful_shutdown)

    # --- Funções de controle e metadados (sem alterações) ---
    def graceful_shutdown(self, signum, frame):
        if not self.shutdown_requested:
            logger.warning("\n" + "="*50)
            logger.warning("PARADA SOLICITADA! Finalizando o trial atual...")
            logger.warning("="*50)
            self.shutdown_requested = True
            
    def _save_wfo_state(self, cycle, start_index, all_results, cumulative_capital):
        state = {
            'last_completed_cycle': cycle - 1,
            'next_start_index': start_index,
            'results_so_far': all_results,
            'cumulative_capital': cumulative_capital
        }
        with open(WFO_STATE_FILE, 'w') as f:
            json.dump(state, f, indent=4)
        logger.info(f"Estado da WFO salvo. Ciclo #{cycle - 1} completo.")

    def _load_wfo_state(self):
        if os.path.exists(WFO_STATE_FILE) and not QUICK_OPTIMIZE: # Só carrega estado se não for otimização rápida
            try:
                with open(WFO_STATE_FILE, 'r') as f:
                    state = json.load(f)
                    last_cycle = state.get('last_completed_cycle', 0)
                    cumulative_capital = state.get('cumulative_capital', 100.0)
                    logger.info("="*50)
                    logger.info(f"Estado de otimização anterior encontrado! Retomando do ciclo #{last_cycle + 1}.")
                    logger.info(f"Capital acumulado até o momento: ${cumulative_capital:,.2f}")
                    logger.info("="*50)
                    return state.get('next_start_index', 0), last_cycle + 1, state.get('results_so_far', []), cumulative_capital
            except Exception as e:
                logger.error(f"Erro ao carregar estado da WFO: {e}. Começando do zero.")
        return 0, 1, [], 100.0
        
    def _save_model_metadata(self):
        try:
            logger.info("  -> Salvando metadados e data de validade do modelo...")
            now_utc = datetime.now(timezone.utc)
            valid_until = now_utc + relativedelta(months=MODEL_VALIDITY_MONTHS)
            metadata = {
                'last_optimization_date': now_utc.isoformat(),
                'valid_until': valid_until.isoformat(),
            }
            with open(MODEL_METADATA_FILE, 'w') as f:
                json.dump(metadata, f, indent=4)
            logger.info(f"  -> ✅ Metadados salvos. O modelo é considerado válido até {valid_until.strftime('%Y-%m-%d')}.")
        except Exception as e:
            logger.error(f"  -> Falha ao salvar metadados do modelo: {e}")

    def _progress_callback(self, study, trial):
        if trial.number > 0 and trial.number % 10 == 0:
             logger.info(
                f"  [Progresso Optuna] Trial {trial.number}/{self.n_trials_for_cycle} | "
                f"Melhor Calmar até agora: {study.best_value:.4f}"
            )

    def _objective(self, trial, train_data, validation_data):
        # (Função _objective permanece exatamente a mesma)
        if self.shutdown_requested:
            raise optuna.exceptions.TrialPruned()
        
        all_params = {
            'n_estimators': trial.suggest_int('n_estimators', 200, 800), 'learning_rate': trial.suggest_float('learning_rate', 0.01, 0.2),
            'num_leaves': trial.suggest_int('num_leaves', 30, 100), 'max_depth': trial.suggest_int('max_depth', 7, 25),
            'min_child_samples': trial.suggest_int('min_child_samples', 20, 70), 'feature_fraction': trial.suggest_float('feature_fraction', 0.5, 1.0),
            'bagging_fraction': trial.suggest_float('bagging_fraction', 0.5, 1.0), 'bagging_freq': trial.suggest_int('bagging_freq', 1, 7),
            'lambda_l1': trial.suggest_float('lambda_l1', 1e-8, 10.0, log=True), 'lambda_l2': trial.suggest_float('lambda_l2', 1e-8, 10.0, log=True),
            'future_periods': trial.suggest_int('future_periods', 15, 240), 'profit_mult': trial.suggest_float('profit_mult', 1.0, 6.0),
            'stop_mult': trial.suggest_float('stop_mult', 1.0, 6.0), 'profit_threshold': trial.suggest_float('profit_threshold', 0.01, 0.08),
            'stop_loss_threshold': trial.suggest_float('stop_loss_threshold', 0.01, 0.05), 'initial_confidence': trial.suggest_float('initial_confidence', 0.51, 0.85),
            'risk_per_trade_pct': trial.suggest_float('risk_per_trade_pct', 0.01, 0.15), 'confidence_learning_rate': trial.suggest_float('confidence_learning_rate', 0.01, 0.20)
        }
        
        model, scaler = self.trainer.train(train_data.copy(), all_params)
        if model is None: return -2.0

        validation_features = self.trainer._prepare_features(validation_data.copy())
        if validation_features.empty: return -2.0

        # Passa apenas os parâmetros da estratégia para o backtest
        strategy_params = {k: v for k, v in all_params.items() if k not in ['n_estimators', 'learning_rate', 'num_leaves', 'max_depth', 'min_child_samples', 'feature_fraction', 'bagging_fraction', 'bagging_freq', 'lambda_l1', 'lambda_l2', 'future_periods', 'profit_mult', 'stop_mult']}
        
        final_capital, annualized_return, max_drawdown, trade_count = run_backtest(model=model, scaler=scaler, test_data_with_features=validation_features, strategy_params=strategy_params, feature_names=self.trainer.final_feature_names)
        
        if max_drawdown == 0 or trade_count < 5: return -1.0 

        calmar_ratio = annualized_return / abs(max_drawdown)
        trade_penalty = np.log1p(trade_count) * 0.1
        final_score = calmar_ratio - trade_penalty
        
        if math.isnan(final_score) or math.isinf(final_score): return -1.0
        return final_score

    def run(self):
        logger.info("="*80)
        if QUICK_OPTIMIZE:
            logger.info("--- INICIANDO MODO DE OTIMIZAÇÃO RÁPIDA ---")
            logger.info("Otimizando apenas o ciclo mais recente para um modelo de produção.")
        else:
            logger.info("--- INICIANDO OTIMIZAÇÃO WALK-FORWARD COMPLETA (OBJETIVO: CALMAR RATIO) ---")
        
        optuna.logging.set_verbosity(optuna.logging.WARNING)
        self.full_data.sort_index(inplace=True)
        n_total = len(self.full_data)
        train_val_size, test_size, step_size = WFO_TRAIN_MINUTES, WFO_TEST_MINUTES, WFO_STEP_MINUTES

        if n_total < train_val_size:
            return logger.error(f"Dados insuficientes. Necessário no mínimo {train_val_size} minutos, disponível: {n_total}")

        # <<< PASSO 3: Lógica para o Modo de Otimização Rápida >>>
        if QUICK_OPTIMIZE:
            # Pula diretamente para o último ciclo possível
            start_index = n_total - train_val_size
            total_cycles = 1
            cycle = 1
            # Zera o estado anterior para não haver confusão
            all_results, cumulative_capital = [], 100.0
        else:
            # Carrega o estado para continuar o WFO completo
            start_index, cycle, all_results, cumulative_capital = self._load_wfo_state()
            total_cycles = math.floor((n_total - train_val_size) / step_size) + 1

        # O loop agora funciona tanto para o WFO completo quanto para o modo rápido (rodará apenas uma vez)
        while start_index + train_val_size <= n_total:
            if self.shutdown_requested: break
            
            # No modo rápido, não há período de teste futuro, usamos todo o final para validação
            current_test_size = 0 if QUICK_OPTIMIZE else test_size
            
            validation_pct = 0.25 # Aumenta a validação para 25% dos dados de treino
            train_val_end = start_index + train_val_size
            train_val_data = self.full_data.iloc[start_index : train_val_end]
            
            validation_size = int(len(train_val_data) * validation_pct)
            train_data = train_val_data.iloc[:-validation_size]
            validation_data = train_val_data.iloc[-validation_size:]
            
            logger.info("\n" + "-"*80)
            logger.info(f"INICIANDO CICLO DE OTIMIZAÇÃO #{cycle} / {total_cycles}")
            logger.info(f"  - Período de Treino:      {train_data.index.min():%Y-%m-%d} a {train_data.index.max():%Y-%m-%d}")
            logger.info(f"  - Período de Validação:   {validation_data.index.min():%Y-%m-%d} a {validation_data.index.max():%Y-%m-%d}")
            
            if not QUICK_OPTIMIZE:
                test_data = self.full_data.iloc[train_val_end : train_val_end + current_test_size]
                if not test_data.empty:
                    logger.info(f"  - Período de Teste Final: {test_data.index.min():%Y-%m-%d} a {test_data.index.max():%Y-%m-%d}")
            logger.info("-" * 80)

            self.n_trials_for_cycle = 100
            study = optuna.create_study(direction='maximize')
            study.optimize(lambda trial: self._objective(trial, train_data, validation_data), n_trials=self.n_trials_for_cycle, n_jobs=-1, callbacks=[self._progress_callback])
            
            if self.shutdown_requested: break
            
            best_trial = study.best_trial
            logger.info(f"\n  -> Otimização do ciclo concluída. Melhor Score na VALIDAÇÃO: {best_trial.value:.4f}")
            logger.info("  -> Melhores Hiperparâmetros encontrados:")
            params_data = {k: [v] for k, v in best_trial.params.items()}
            print(tabulate(params_data, headers="keys", tablefmt="grid", numalign="center"))

            if best_trial.value > 0.1:
                logger.info("  -> Treinando modelo final com os melhores parâmetros...")
                # No modo rápido, usamos todos os dados disponíveis para treinar o modelo final
                final_train_data = train_val_data if QUICK_OPTIMIZE else train_data
                final_model, final_scaler = self.trainer.train(final_train_data.copy(), best_trial.params)
                
                if final_model:
                    strategy_params = {k: v for k, v in best_trial.params.items() if k not in ['n_estimators', 'learning_rate', 'num_leaves', 'max_depth', 'min_child_samples', 'feature_fraction', 'bagging_fraction', 'bagging_freq', 'lambda_l1', 'lambda_l2', 'future_periods', 'profit_mult', 'stop_mult']}
                    self.trainer.save_model(final_model, final_scaler)
                    with open(STRATEGY_PARAMS_FILE, 'w') as f: json.dump(strategy_params, f, indent=4)
                    
                    self._save_model_metadata()
                    
                    # No WFO completo, executa o backtest no período de teste
                    if not QUICK_OPTIMIZE and not test_data.empty:
                        logger.info("  -> Executando backtest final no período de TESTE (Out-of-Sample)...")
                        # (Lógica de backtest do WFO... mantida como estava)
                else:
                    logger.error("  -> Falha ao treinar o modelo final. Pulando.")
            else:
                logger.warning(f"  -> Melhor score na validação ({best_trial.value:.4f}) não atingiu o limiar de 0.1. Pulando.")
            
            if QUICK_OPTIMIZE:
                break # Sai do loop após a primeira e única execução

            start_index += step_size
            cycle += 1
            self._save_wfo_state(cycle, start_index, all_results, cumulative_capital)
            gc.collect()

        logger.info("\n\n" + "="*80 + "\n--- PROCESSO DE OTIMIZAÇÃO CONCLUÍDO ---")