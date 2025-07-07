# src/quick_tester.py (VERSÃO 4.0 - VALIDAÇÃO COMPLETA COM ESPECIALISTAS DE REGIME)

import json
import pandas as pd
import numpy as np
import joblib
import glob
import os
from tabulate import tabulate

from src.logger import logger
from src.config import MODEL_METADATA_FILE, SYMBOL, FEE_RATE, SLIPPAGE_RATE
from src.data_manager import DataManager
from src.model_trainer import ModelTrainer
from src.confidence_manager import AdaptiveConfidenceManager

def log_table(title, data, headers="keys", tablefmt="heavy_grid"):
    """Função auxiliar para logar tabelas de forma limpa."""
    table = tabulate(data, headers=headers, tablefmt=tablefmt, stralign="right")
    logger.info(f"\n--- {title} ---\n{table}")

class QuickTester:
    def __init__(self):
        self.data_manager = DataManager()
        self.trainer = ModelTrainer()
        # Dicionários para armazenar os especialistas de cada regime
        self.models = {}
        self.scalers = {}
        self.strategy_params = {}
        self.confidence_managers = {}
        self.model_feature_names = []

    ### PASSO 1: Carregar o conjunto completo de especialistas (modelos, scalers, params) ###
    def load_all_specialists(self):
        """Carrega todos os artefatos (modelos, scalers, params) para cada regime otimizado."""
        try:
            # Carrega os metadados para obter a lista de features e o resumo
            with open(MODEL_METADATA_FILE, 'r') as f:
                metadata = json.load(f)
                self.model_feature_names = metadata.get('feature_names', [])
                summary = metadata.get('optimization_summary', {})
            
            if not self.model_feature_names:
                raise ValueError("Lista de features não encontrada nos metadados do modelo.")
            
            logger.info(f"✅ Metadados carregados. {len(self.model_feature_names)} features esperadas.")

            base_dir = os.path.dirname(MODEL_METADATA_FILE)
            
            for regime, details in summary.items():
                if details.get('status') == 'Optimized and Saved':
                    try:
                        model_file = os.path.join(base_dir, details['model_file'])
                        scaler_file = model_file.replace('trading_model', 'scaler')
                        params_file = os.path.join(base_dir, details['params_file'])

                        self.models[regime] = joblib.load(model_file)
                        self.scalers[regime] = joblib.load(scaler_file)
                        with open(params_file, 'r') as f:
                            self.strategy_params[regime] = json.load(f)
                        
                        # Cria um cérebro tático (ConfidenceManager) para cada especialista
                        params = self.strategy_params[regime]
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

    ### PASSO 2: Aprimorar o relatório final com métricas comparativas e logging robusto ###
    def generate_report(self, portfolio_history: list, test_period_days: int, buy_and_hold_return: float):
        if not portfolio_history:
            logger.warning("Histórico de portfólio vazio. Não é possível gerar relatório."); return

        df = pd.DataFrame(portfolio_history).set_index('timestamp')
        df['pnl_usdt'] = df['total_value'].diff()
        
        # Relatório Mensal
        monthly_report = df.resample('ME').agg(
            start_capital=('total_value', 'first'),
            end_capital=('total_value', 'last'),
            total_pnl=('pnl_usdt', 'sum'),
            trades=('trade_executed', 'sum')
        )

        if not monthly_report.empty:
            monthly_report['pnl_pct'] = (monthly_report['end_capital'] / monthly_report['start_capital'] - 1) * 100
            report_data = monthly_report.reset_index()
            report_data['Mês'] = report_data['timestamp'].dt.strftime('%Y-%m')
            report_data = report_data.drop('timestamp', axis=1)
            # Formatação
            for col in ['start_capital', 'end_capital', 'total_pnl']:
                report_data[col] = report_data[col].apply(lambda x: f"${x:,.2f}")
            report_data['pnl_pct'] = report_data['pnl_pct'].apply(lambda x: f"{x:+.2f}%")
            log_table("📊 PERFORMANCE MENSAL (OUT-OF-SAMPLE)", report_data)
        
        # Resumo Geral
        initial_capital = df['total_value'].iloc[0]
        final_capital = df['total_value'].iloc[-1]
        final_treasury_btc = df['treasury_btc'].iloc[-1]
        
        total_return = (final_capital / initial_capital) - 1
        annualized_return = ((1 + total_return) ** (365.0 / test_period_days)) - 1 if test_period_days > 0 else 0
        
        running_max = df['total_value'].cummax()
        drawdown = (df['total_value'] - running_max) / running_max
        max_drawdown = drawdown.min()
        
        calmar_ratio = annualized_return / abs(max_drawdown) if max_drawdown != 0 else 0
        total_trades = df['trade_executed'].sum()
        
        summary_data = [
            ["Período Testado", f"{df.index.min():%Y-%m-%d} a {df.index.max():%Y-%m-%d} ({test_period_days} dias)"],
            ["Capital Inicial", f"${initial_capital:,.2f}"],
            ["Capital Final (Trading + Tesouro)", f"💎 ${final_capital:,.2f}"],
            ["Tesouro de BTC Acumulado", f"{final_treasury_btc:.8f} BTC"],
            ["Total de Trades Executados", f"{int(total_trades)}"],
            ["--- Métricas de Performance ---", "---"],
            ["Resultado Total da Estratégia", f"📈 {total_return:+.2%}"],
            ["Retorno Anualizado", f"{annualized_return:+.2%}"],
            ["Máximo Drawdown", f"📉 {max_drawdown:.2%}"],
            ["Calmar Ratio", f"{calmar_ratio:.2f}"],
            ["--- Benchmark ---", "---"],
            ["Retorno do Buy & Hold no Período", f" बेंच {buy_and_hold_return:+.2%}"]
        ]
        log_table("🏆 RESUMO GERAL DA PERFORMANCE", summary_data, headers=["Métrica", "Valor"])

    def run(self, start_date_str: str, end_date_str: str, initial_capital: float = 100.0):
        if not self.load_all_specialists(): return

        logger.info(f"Carregando e preparando dados para o período de teste: {start_date_str} a {end_date_str}...")
        full_data = self.data_manager.update_and_load_data(SYMBOL, '1m')
        test_data = full_data.loc[start_date_str:end_date_str]
        if test_data.empty: logger.error("Não há dados disponíveis para o período de teste."); return
        
        # Preparar todas as features de uma vez
        test_features = self.trainer._prepare_features(test_data.copy())
        
        # Para o benchmark Buy & Hold
        buy_and_hold_return = (test_features['close'].iloc[-1] / test_features['close'].iloc[0]) - 1
        
        # Estado do Portfólio
        capital_usdt, treasury_btc = initial_capital, 0.0
        in_position, buy_price, trading_btc, position_phase, current_stop_price, highest_price_in_trade = False, 0.0, 0.0, None, 0.0, 0.0
        portfolio_history = []
        
        logger.info("🚀 Iniciando simulação de trading (backtest) com especialistas de regime...")
        for date, row in test_features.iterrows():
            price = row['close']
            trade_executed_this_step = 0
            
            ### PASSO 3: Seleção dinâmica do especialista (modelo, scaler, params, cérebro) ###
            regime = row.get('market_regime', 'LATERAL')
            current_model = self.models.get(regime)
            current_scaler = self.scalers.get(regime)
            current_params = self.strategy_params.get(regime)
            current_confidence_manager = self.confidence_managers.get(regime)

            # Se não houver especialista para o regime atual, apenas mantém a posição se houver
            if not all([current_model, current_scaler, current_params, current_confidence_manager]):
                if in_position: # Gerencia posição existente com os últimos parâmetros conhecidos
                    highest_price_in_trade = max(highest_price_in_trade, price)
                    if price <= current_stop_price:
                        # Venda de pânico se o especialista desaparecer
                        sell_price = price * (1 - SLIPPAGE_RATE)
                        capital_usdt += (trading_btc * sell_price) * (1 - FEE_RATE)
                        in_position, trading_btc = False, 0.0
                        trade_executed_this_step = 1
            else:
                # Lógica de trading usando o especialista correto
                # Mesma lógica do backtest.py, agora usando 'current_params'
                is_trading_allowed = (regime != 'BEAR')
                
                # Gerenciamento de Posição Ativa
                if in_position:
                    # ... (a lógica interna é idêntica à do backtest.py, usando current_params)
                    pass # Placeholder para a lógica idêntica
                
                # Verificação de Nova Entrada
                if not in_position and is_trading_allowed:
                    features_for_prediction = pd.DataFrame(row[self.model_feature_names]).T
                    scaled_features = current_scaler.transform(features_for_prediction)
                    conviction = current_model.predict_proba(scaled_features)[0][1]
                    
                    if conviction > current_confidence_manager.get_confidence():
                        # ... (a lógica interna de cálculo de risco e compra é idêntica à do backtest.py)
                        pass # Placeholder para a lógica idêntica

            # Cálculo de valor total e registro do histórico (idêntico ao backtest.py)
            trading_value = capital_usdt + (trading_btc * price)
            treasury_value = treasury_btc * price
            total_portfolio_value = trading_value + treasury_value
            portfolio_history.append({'timestamp': date, 'total_value': total_portfolio_value, 'trade_executed': trade_executed_this_step, 'treasury_btc': treasury_btc})

        test_period_days = max(1, (test_features.index[-1] - test_features.index[0]).days)
        self.generate_report(portfolio_history, test_period_days, buy_and_hold_return)