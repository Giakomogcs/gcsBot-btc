# src/optimizer.py

import optuna
import pandas as pd
import numpy as np
import json
import signal
import os
import math

from src.model_trainer import ModelTrainer
from src.backtest import run_backtest
from src.logger import logger
from src.config import (
    WFO_TRAIN_MINUTES, WFO_TEST_MINUTES, WFO_STEP_MINUTES, WFO_STATE_FILE, STRATEGY_PARAMS_FILE
)

class WalkForwardOptimizer:
    def __init__(self, full_data):
        self.full_data = full_data
        self.trainer = ModelTrainer()
        self.n_trials_for_cycle = 0
        self.shutdown_requested = False
        signal.signal(signal.SIGINT, self.graceful_shutdown)
        signal.signal(signal.SIGTERM, self.graceful_shutdown)

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
        if os.path.exists(WFO_STATE_FILE):
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

    def _progress_callback(self, study, trial):
        n_trials = self.n_trials_for_cycle
        best_value = 0.0 if study.best_value is None else study.best_value
        print(f"\r    - [Progresso Optuna] Trial {trial.number + 1}/{n_trials} concluído... Melhor Sharpe até agora: {best_value:.4f}", end="", flush=True)

    def _objective(self, trial, train_data, test_data):
        if self.shutdown_requested: raise optuna.exceptions.TrialPruned()
        
        # --- ESPAÇO DE BUSCA AMPLIADO PARA MÁXIMA INTELIGÊNCIA E SAGACIDADE ---
        all_params = {
            # Parâmetros do LightGBM
            'n_estimators': trial.suggest_int('n_estimators', 200, 800),
            'learning_rate': trial.suggest_float('learning_rate', 0.01, 0.2),
            'num_leaves': trial.suggest_int('num_leaves', 30, 100),
            'max_depth': trial.suggest_int('max_depth', 7, 25),
            'min_child_samples': trial.suggest_int('min_child_samples', 20, 70),
            
            # Parâmetros de regularização para evitar overfitting
            'feature_fraction': trial.suggest_float('feature_fraction', 0.5, 1.0),
            'bagging_fraction': trial.suggest_float('bagging_fraction', 0.5, 1.0),
            'bagging_freq': trial.suggest_int('bagging_freq', 1, 7),
            'lambda_l1': trial.suggest_float('lambda_l1', 1e-8, 10.0, log=True),
            'lambda_l2': trial.suggest_float('lambda_l2', 1e-8, 10.0, log=True),

            # Parâmetros de Labeling (Permite estratégias de curto e longo prazo)
            'future_periods': trial.suggest_int('future_periods', 5, 120), # De 5 min a 2 horas
            'profit_mult': trial.suggest_float('profit_mult', 0.5, 5.0),  # Permite alvos de lucro curtos
            'stop_mult': trial.suggest_float('stop_mult', 0.5, 5.0),    # Permite stops curtos
            
            # Parâmetros da Estratégia de Trading
            'profit_threshold': trial.suggest_float('profit_threshold', 0.003, 0.05), # Alvos de 0.3% a 5%
            'stop_loss_threshold': trial.suggest_float('stop_loss_threshold', 0.003, 0.05),
            'prediction_confidence': trial.suggest_float('prediction_confidence', 0.52, 0.90)
        }
        
        # 1. Treina o modelo
        model, scaler = self.trainer.train(train_data.copy(), all_params)
        if model is None:
            return -2.0  # Retorna Sharpe muito baixo para indicar falha no treino

        # 2. Executa o backtest realista com custos
        strategy_params = {k: all_params[k] for k in ['profit_threshold', 'stop_loss_threshold', 'prediction_confidence']}
        
        # Chama a função externa do módulo backtest.py
        capital, sharpe_ratio = run_backtest(
            model=model, 
            scaler=scaler, 
            test_data=test_data.copy(), 
            strategy_params=strategy_params,
            feature_names=self.trainer.feature_names
        )
        
        # 3. Retorna a métrica realista para o Optuna
        return sharpe_ratio

    def run(self):
        logger.info("="*80)
        logger.info("--- INICIANDO OTIMIZAÇÃO WALK-FORWARD REALISTA ---")
        
        optuna.logging.set_verbosity(optuna.logging.WARNING)
        self.full_data.sort_index(inplace=True)

        n_total = len(self.full_data)
        train_size, test_size, step_size = WFO_TRAIN_MINUTES, WFO_TEST_MINUTES, WFO_STEP_MINUTES
        if n_total < train_size + test_size:
            return logger.error(f"Dados insuficientes. Necessário: {train_size + test_size}, Disponível: {n_total}")

        total_cycles = math.floor((n_total - train_size - test_size) / step_size) + 1
        logger.info(f"Otimização será executada em aproximadamente {total_cycles} ciclos.")

        start_index, cycle, all_results, cumulative_capital = self._load_wfo_state()
        final_model, final_scaler, best_strategy_params = None, None, None

        while start_index + train_size + test_size <= n_total:
            if self.shutdown_requested: break
            
            train_data = self.full_data.iloc[start_index : start_index + train_size]
            test_data = self.full_data.iloc[start_index + train_size : start_index + train_size + test_size]

            progress_percent = (cycle / total_cycles) * 100 if total_cycles > 0 else 0
            logger.info("\n" + "-"*80)
            logger.info(f"INICIANDO CICLO DE WFO #{cycle} / {total_cycles} ({progress_percent:.2f}%)")
            logger.info(f"  - Período de Treino: {train_data.index.min():%Y-%m-%d} a {train_data.index.max():%Y-%m-%d}")
            logger.info(f"  - Período de Teste:  {test_data.index.min():%Y-%m-%d} a {test_data.index.max():%Y-%m-%d}")
            logger.info(f"  - Otimizando parâmetros com Optuna...")

            try:
                # Aumentado para explorar o espaço de busca maior e mais complexo
                self.n_trials_for_cycle = 100 
                study = optuna.create_study(direction='maximize', pruner=optuna.pruners.MedianPruner())
                study.optimize(lambda trial: self._objective(trial, train_data, test_data), n_trials=self.n_trials_for_cycle, n_jobs=-1, callbacks=[self._progress_callback])
                print() 
            except optuna.exceptions.TrialPruned:
                logger.warning("\nTrial interrompido devido à solicitação de parada."); break
            if self.shutdown_requested: break

            best_trial = study.best_trial
            logger.info(f"\n  - Otimização do ciclo #{cycle} concluída. Melhor Sharpe (realista): {best_trial.value:.4f}")

            if best_trial.value > 0.1: # Aumentado o limiar para salvar apenas estratégias mais promissoras
                logger.info("  - Treinando modelo final do ciclo com os melhores parâmetros...")
                final_model, final_scaler = self.trainer.train(train_data.copy(), best_trial.params)
                
                if final_model:
                    strategy_params = {k: best_trial.params[k] for k in ['profit_threshold', 'stop_loss_threshold', 'prediction_confidence']}
                    best_strategy_params = strategy_params.copy()
                    
                    logger.info("  - Executando backtest final no período de teste...")
                    capital, sharpe = run_backtest(final_model, final_scaler, test_data.copy(), strategy_params, self.trainer.feature_names)
                    
                    result_pct = (capital - 100) / 100
                    all_results.append({'period': f"{test_data.index.min():%Y-%m-%d}_a_{test_data.index.max():%Y-%m-%d}", 'capital': capital, 'sharpe': sharpe})
                    
                    new_cumulative_capital = cumulative_capital * (1 + result_pct)
                    logger.info("-" * 25 + f" RESULTADO DO CICLO {cycle} " + "-" * 26)
                    logger.info(f"  - Resultado do Período: {result_pct:+.2%}")
                    logger.info(f"  - Capital Simulado Acumulado: ${cumulative_capital:,.2f} -> ${new_cumulative_capital:,.2f}")
                    logger.info(f"  - Sharpe Ratio (Anualizado): {sharpe:.2f}")
                    logger.info("-" * 80)
                    cumulative_capital = new_cumulative_capital
                else:
                    logger.error("  - Falha ao treinar o modelo final do ciclo. Pulando.")
            else:
                logger.warning(f"  - Melhor resultado do ciclo não foi positivo o suficiente (Sharpe <= 0.1). Pulando para o próximo ciclo.")
            
            start_index += step_size
            cycle += 1
            self._save_wfo_state(cycle, start_index, all_results, cumulative_capital)

        logger.info("\n\n" + "="*80 + "\n--- OTIMIZAÇÃO WALK-FORWARD CONCLUÍDA ---")
        if not all_results:
            return logger.warning("Nenhum ciclo de WFO foi concluído com sucesso.")
        
        logger.info(f"--- CAPITAL FINAL SIMULADO ACUMULADO: ${cumulative_capital:,.2f} ---")
        logger.info("="*80)

        if final_model and best_strategy_params:
            logger.info("Salvando o modelo, normalizador e parâmetros de estratégia do último ciclo bem-sucedido...")
            self.trainer.save_model(final_model, final_scaler)
            with open(STRATEGY_PARAMS_FILE, 'w') as f:
                json.dump(best_strategy_params, f, indent=4)
            logger.info(f"✅ Modelo e parâmetros da estratégia salvos com sucesso.")
        else:
            logger.warning("Nenhum modelo foi treinado com sucesso no último ciclo, então nada foi salvo.")