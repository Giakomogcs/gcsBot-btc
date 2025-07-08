# src/quick_tester.py (VERSÃO 5.0 - SIMULADOR ROBUSTO)

import json
import pandas as pd
import numpy as np
import joblib
import os
from lightgbm import LGBMClassifier
from sklearn.preprocessing import StandardScaler

from src.logger import logger, log_table
from src.config import MODEL_METADATA_FILE, SYMBOL, DATA_DIR, FEE_RATE, SLIPPAGE_RATE
from src.data_manager import DataManager
from src.model_trainer import ModelTrainer # Usado para o _prepare_features
from src.confidence_manager import AdaptiveConfidenceManager

# --- NOVO --- Função para calcular o Sortino Ratio, igual à do backtest.py
def calculate_sortino_ratio(series, periods_per_year=365*24*60):
    returns = series.pct_change().dropna()
    target_return = 0
    downside_returns = returns[returns < target_return]
    
    expected_return = returns.mean()
    downside_std = downside_returns.std()
    
    if downside_std == 0 or pd.isna(downside_std): return 0.0
        
    sortino = (expected_return * periods_per_year) / (downside_std * np.sqrt(periods_per_year))
    return sortino if not pd.isna(sortino) else 0.0

class QuickTester:
    def __init__(self):
        self.data_manager = DataManager()
        self.trainer = ModelTrainer() 
        
        self.models = {}
        self.scalers = {}
        self.strategy_params = {}
        self.confidence_managers = {}
        self.model_feature_names = []

    def load_all_specialists(self):
        """Carrega todos os artefatos (modelos, scalers, params) para cada regime otimizado."""
        try:
            with open(MODEL_METADATA_FILE, 'r') as f:
                metadata = json.load(f)
            self.model_feature_names = metadata.get('feature_names', [])
            summary = metadata.get('optimization_summary', {})
            
            if not self.model_feature_names:
                raise ValueError("Lista de features não encontrada nos metadados do modelo.")
            
            logger.info(f"✅ Metadados carregados. {len(self.model_feature_names)} features esperadas.")

            base_dir = DATA_DIR
            
            for regime, details in summary.items():
                if details.get('status') == 'Optimized and Saved':
                    try:
                        model_path = os.path.join(base_dir, details['model_file'])
                        # --- MUDANÇA --- Caminho do scaler corrigido para ser mais robusto
                        scaler_path = os.path.join(base_dir, details['model_file'].replace('trading_model', 'scaler'))
                        params_path = os.path.join(base_dir, details['params_file'])

                        self.models[regime] = joblib.load(model_path)
                        self.scalers[regime] = joblib.load(scaler_path)
                        with open(params_path, 'r') as f:
                            params = json.load(f)
                            self.strategy_params[regime] = params
                        
                        self.confidence_managers[regime] = AdaptiveConfidenceManager(
                            initial_confidence=params.get('initial_confidence', 0.6),
                            learning_rate=params.get('confidence_learning_rate', 0.05),
                            window_size=params.get('confidence_window_size', 5)
                        )
                        logger.info(f"-> Especialista para o regime '{regime}' carregado com sucesso.")
                    except Exception as e:
                        logger.error(f"-> Falha ao carregar especialista para o regime '{regime}': {e}")
                        
            if not self.models:
                logger.error("Nenhum modelo especialista foi carregado com sucesso.")
                return False

            return True

        except FileNotFoundError:
            logger.error(f"ERRO: Arquivo de metadados '{MODEL_METADATA_FILE}' não encontrado. Execute a otimização primeiro.")
            return False
        except Exception as e:
            logger.error(f"Erro inesperado ao carregar especialistas: {e}", exc_info=True)
            return False

    def generate_report(self, portfolio_history: list, test_period_days: int, buy_and_hold_return: float):
        if not portfolio_history:
            logger.warning("Histórico de portfólio vazio. Não é possível gerar relatório."); return

        df = pd.DataFrame(portfolio_history).set_index('timestamp')
        
        initial_capital = df['total_value'].iloc[0]
        final_capital = df['total_value'].iloc[-1]
        
        total_return = (final_capital / initial_capital) - 1
        annualized_return = ((1 + total_return) ** (365.0 / test_period_days)) - 1 if test_period_days > 0 else 0
        
        running_max = df['total_value'].cummax()
        drawdown = (df['total_value'] - running_max) / running_max
        max_drawdown = drawdown.min()
        
        # --- NOVO --- Adicionando o Sortino Ratio ao relatório
        sortino_ratio = calculate_sortino_ratio(df['total_value'])
        calmar_ratio = annualized_return / abs(max_drawdown) if max_drawdown != 0 else 0
        total_trades = df['trade_executed'].sum()
        
        summary_data = [
            ["Período Testado", f"{df.index.min():%Y-%m-%d} a {df.index.max():%Y-%m-%d} ({test_period_days} dias)"],
            ["Capital Inicial", f"${initial_capital:,.2f}"],
            ["Capital Final", f"💎 ${final_capital:,.2f}"],
            ["Total de Trades Executados", f"{int(total_trades)}"],
            ["--- Métricas de Performance ---", ""],
            ["Resultado Total da Estratégia", f"📈 {total_return:+.2%}"],
            ["Retorno Anualizado", f"{annualized_return:+.2%}"],
            ["Máximo Drawdown", f"📉 {max_drawdown:.2%}"],
            ["Calmar Ratio", f"{calmar_ratio:.2f}"],
            ["Sortino Ratio", f"🍀 {sortino_ratio:.2f}"], # NOVO
            ["--- Benchmark ---", ""],
            ["Retorno do Buy & Hold", f"벤치 {buy_and_hold_return:+.2%}"]
        ]
        log_table("🏆 RESUMO GERAL DA PERFORMANCE (OUT-OF-SAMPLE)", summary_data, headers=["Métrica", "Valor"])

    def run(self, start_date_str: str, end_date_str: str, initial_capital: float = 100.0):
        if not self.load_all_specialists(): return

        logger.info(f"Carregando e preparando dados para o período de teste: {start_date_str} a {end_date_str}...")
        full_data = self.data_manager.update_and_load_data(SYMBOL, '1m')
        test_data = full_data.loc[start_date_str:end_date_str]
        if test_data.empty: 
            logger.error("Não há dados disponíveis para o período de teste."); return
        
        # --- MUDANÇA --- Usando o _prepare_features do trainer para consistência
        test_features_df, _ = self.trainer._prepare_features(test_data.copy())
        
        buy_and_hold_return = (test_features_df['close'].iloc[-1] / test_features_df['close'].iloc[0]) - 1
        
        capital_usdt = initial_capital
        in_position, buy_price, trading_btc, position_phase, current_stop_price, highest_price_in_trade = False, 0.0, 0.0, None, 0.0, 0.0
        portfolio_history = []
        last_used_params = {}
        
        logger.info("🚀 Iniciando simulação de trading (backtest) com especialistas de regime...")
        for date, row in test_features_df.iterrows():
            price = row['close']
            trade_executed_this_step = 0
            
            regime = row.get('market_regime', 'LATERAL')
            params = last_used_params if in_position else self.strategy_params.get(regime)

            if not params:
                 if in_position: # Se entrar em um regime sem especialista, apenas gerencia a posição
                    highest_price_in_trade = max(highest_price_in_trade, price)
                    if price <= current_stop_price:
                        sell_price = price * (1 - SLIPPAGE_RATE)
                        capital_usdt += (trading_btc * sell_price) * (1 - FEE_RATE)
                        in_position, trading_btc = False, 0.0; trade_executed_this_step = 1
            else:
                is_trading_allowed = (regime != 'BEAR')
                
                if in_position:
                    highest_price_in_trade = max(highest_price_in_trade, price)
                    stop_loss_atr_multiplier = params.get('stop_loss_atr_multiplier', 2.5)

                    if price <= current_stop_price:
                        sell_price = price * (1 - SLIPPAGE_RATE)
                        capital_usdt += (trading_btc * sell_price) * (1 - FEE_RATE)
                        pnl = (sell_price / buy_price) - 1 if buy_price > 0 else 0
                        confidence_manager = self.confidence_managers.get(params.get('entry_regime'))
                        if confidence_manager: confidence_manager.update(pnl)
                        in_position, trading_btc, last_used_params = False, 0.0, {}
                        trade_executed_this_step = 1
                    
                    elif position_phase == 'INITIAL' and price >= buy_price * (1 + params.get('profit_threshold', 0.01) / 2):
                        position_phase = 'BREAKEVEN'
                        current_stop_price = buy_price * (1 + (FEE_RATE * 2))
                    
                    # --- MUDANÇA --- Trailing stop também usa ATR
                    elif position_phase == 'TRAILING':
                        trailing_stop_multiplier = params.get('trailing_stop_multiplier', 1.5)
                        new_trailing_stop = highest_price_in_trade - (row['atr'] * stop_loss_atr_multiplier * trailing_stop_multiplier)
                        current_stop_price = max(current_stop_price, new_trailing_stop)

                if not in_position and is_trading_allowed:
                    model, scaler = self.models.get(regime), self.scalers.get(regime)
                    confidence_manager = self.confidence_managers.get(regime)
                    
                    if model and scaler and confidence_manager:
                        # --- NOVO: FILTRO DE VOLUME ---
                        if row['volume'] < row['volume_sma_50']:
                            continue # Pula para a próxima vela

                        features_for_prediction = pd.DataFrame(row[self.model_feature_names]).T
                        scaled_features = scaler.transform(features_for_prediction)
                        buy_confidence = model.predict_proba(scaled_features)[0][1]
                        
                        if buy_confidence > confidence_manager.get_confidence():
                            # --- NOVA LÓGICA DE RISCO AGRESSIVO E ROBUSTO ---
                            base_risk = params.get('risk_per_trade_pct', 0.05)
                            if regime == 'RECUPERACAO': base_risk /= 2
                            
                            signal_strength = (buy_confidence - confidence_manager.get_confidence()) / (1.0 - confidence_manager.get_confidence())
                            aggression_exponent = params.get('aggression_exponent', 2.0)
                            max_risk_scale = params.get('max_risk_scale', 3.0)
                            aggression_factor = 0.5 + (signal_strength ** aggression_exponent) * (max_risk_scale - 0.5)
                            dynamic_risk_pct = base_risk * aggression_factor
                            
                            trade_size_usdt = capital_usdt * dynamic_risk_pct

                            # AJUSTE PELA VOLATILIDADE
                            current_atr = row.get('atr', 0)
                            long_term_atr = row.get('atr_long_avg', current_atr)
                            if long_term_atr > 0 and current_atr > 0:
                                volatility_factor = current_atr / long_term_atr
                                risk_dampener = np.clip(1 / volatility_factor, 0.6, 1.2)
                                trade_size_usdt *= risk_dampener
                            # -----------------------------------------------

                            if capital_usdt > 10 and trade_size_usdt > 10:
                                buy_price_eff = price * (1 + SLIPPAGE_RATE)
                                amount_to_buy_btc = trade_size_usdt / buy_price_eff
                                
                                in_position = True
                                trading_btc = amount_to_buy_btc
                                capital_usdt -= trade_size_usdt * (1 + FEE_RATE)
                                buy_price = buy_price_eff
                                # --- MUDANÇA: STOP LOSS COM ATR ---
                                current_stop_price = buy_price_eff - (row['atr'] * params.get('stop_loss_atr_multiplier', 2.5))
                                
                                highest_price_in_trade = buy_price_eff
                                position_phase = 'INITIAL'
                                last_used_params = {**params, 'entry_regime': regime}
                                trade_executed_this_step = 1

            total_portfolio_value = capital_usdt + (trading_btc * price)
            portfolio_history.append({'timestamp': date, 'total_value': total_portfolio_value, 'trade_executed': trade_executed_this_step})

        test_period_days = max(1, (test_features_df.index[-1] - test_features_df.index[0]).days)
        self.generate_report(portfolio_history, test_period_days, buy_and_hold_return)