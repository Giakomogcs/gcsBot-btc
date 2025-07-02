# src/quick_tester.py (VERSÃO FINAL COM INTELIGÊNCIA ADAPTATIVA)

import json
import pandas as pd
import numpy as np
import joblib
from tabulate import tabulate

from src.logger import logger
from src.config import MODEL_FILE, SCALER_FILE, STRATEGY_PARAMS_FILE, SYMBOL
from src.data_manager import DataManager
from src.model_trainer import ModelTrainer
# <<< PASSO 1: Importar o cérebro adaptativo >>>
from src.confidence_manager import AdaptiveConfidenceManager

# Constantes de custo para a simulação
FEE_RATE = 0.001
SLIPPAGE_RATE = 0.0005

class QuickTester:
    """
    Realiza um backtest de validação (out-of-sample) de um modelo treinado,
    simulando a gestão de confiança adaptativa e risco dinâmico para gerar
    um relatório de performance completo.
    """
    def __init__(self):
        self.data_manager = DataManager()
        self.trainer = ModelTrainer()
        self.model = None
        self.scaler = None
        self.strategy_params = {}

    def load_model_and_params(self):
        """Carrega o modelo, normalizador e TODOS os parâmetros otimizados."""
        try:
            self.model = joblib.load(MODEL_FILE)
            self.scaler = joblib.load(SCALER_FILE)
            with open(STRATEGY_PARAMS_FILE, 'r') as f:
                self.strategy_params = json.load(f)
            logger.info("✅ Modelo, normalizador e parâmetros da estratégia carregados com sucesso.")
            return True
        except FileNotFoundError as e:
            logger.error(f"ERRO: Arquivo '{e.filename}' não encontrado. Execute o modo 'optimize' para gerar um modelo primeiro.")
            return False

    def generate_report(self, portfolio_history):
        """Gera e imprime um relatório de performance mensal e geral."""
        if not portfolio_history:
            logger.warning("Histórico de portfólio vazio. Não é possível gerar relatório.")
            return

        df = pd.DataFrame(portfolio_history).set_index('timestamp')
        df['pnl'] = df['value'].diff()
        
        monthly_report = df.resample('ME').agg(
            start_capital=pd.NamedAgg(column='value', aggfunc='first'),
            end_capital=pd.NamedAgg(column='value', aggfunc='last'),
            total_pnl=pd.NamedAgg(column='pnl', aggfunc='sum'),
            trades=pd.NamedAgg(column='trade_executed', aggfunc='sum')
        )
        monthly_report['pnl_pct'] = (monthly_report['end_capital'] / monthly_report['start_capital'] - 1) * 100
        
        monthly_report.index = monthly_report.index.strftime('%Y-%m')
        report_data = monthly_report.reset_index()
        report_data.rename(columns={'index': 'Mês'}, inplace=True)
        
        for col in ['start_capital', 'end_capital', 'total_pnl']:
            report_data[col] = report_data[col].apply(lambda x: f"${x:,.2f}")
        report_data['pnl_pct'] = report_data['pnl_pct'].apply(lambda x: f"{x:,.2f}%")

        logger.info("\n\n" + "="*80)
        logger.info("--- RELATÓRIO DE PERFORMANCE DO BACKTEST (OUT-OF-SAMPLE) ---")
        print(tabulate(report_data, headers='keys', tablefmt='pipe', showindex=False))
        
        initial = df['value'].iloc[0]
        final = df['value'].iloc[-1]
        total_pnl = final - initial
        total_pnl_pct = (final / initial - 1) * 100 if initial > 0 else 0
        total_trades = df['trade_executed'].sum()
        
        logger.info("\n--- RESUMO GERAL ---")
        logger.info(f"Período Testado: {df.index.min():%Y-%m-%d} a {df.index.max():%Y-%m-%d}")
        logger.info(f"Capital Inicial: ${initial:,.2f}")
        logger.info(f"Capital Final: ${final:,.2f}")
        logger.info(f"Lucro/Prejuízo Total: ${total_pnl:,.2f} ({total_pnl_pct:+.2f}%)")
        logger.info(f"Total de Trades Executados: {int(total_trades)}")
        logger.info("="*80)

    def run(self, start_date_str: str, end_date_str: str, initial_capital: float = 1000.0):
        """Executa a simulação de backtest."""
        if not self.load_model_and_params():
            return

        logger.info(f"Carregando e preparando dados para o período de {start_date_str} a {end_date_str}...")
        full_data = self.data_manager.update_and_load_data(SYMBOL, '1m')
        
        test_data = full_data.loc[start_date_str:end_date_str]
        if test_data.empty:
            logger.error(f"Não há dados disponíveis para o período de teste solicitado. Verifique as datas.")
            return

        test_features = self.trainer._prepare_features(test_data.copy())
        
        X_test_scaled_np = self.scaler.transform(test_features[self.trainer.feature_names])
        X_test_scaled_df = pd.DataFrame(X_test_scaled_np, index=test_features.index, columns=self.trainer.feature_names)
        predictions_proba = self.model.predict_proba(X_test_scaled_df)
        predictions_buy_proba = pd.Series(predictions_proba[:, 1], index=test_features.index)

        capital = initial_capital
        btc_amount = 0.0
        in_position = False
        buy_price = 0.0
        portfolio_history = []
        
        # <<< PASSO 2: Carregar os parâmetros otimizados corretos >>>
        base_risk_per_trade = self.strategy_params.get('risk_per_trade_pct')
        initial_conf = self.strategy_params.get('initial_confidence')
        learning_rate = self.strategy_params.get('confidence_learning_rate')
        
        # <<< PASSO 3: Instanciar o cérebro adaptativo >>>
        confidence_manager = AdaptiveConfidenceManager(initial_confidence=initial_conf, learning_rate=learning_rate)
        
        logger.info("Iniciando simulação de trading no período de teste...")
        for date, row in test_features.iterrows():
            price = row['close']
            trade_executed_this_step = 0

            if in_position:
                pnl_pct = (price / buy_price) - 1 if buy_price > 0 else 0
                if (pnl_pct >= self.strategy_params['profit_threshold'] or 
                    pnl_pct <= -self.strategy_params['stop_loss_threshold']):
                    
                    sell_price = price * (1 - SLIPPAGE_RATE)
                    revenue = btc_amount * sell_price
                    capital += revenue * (1 - FEE_RATE)
                    
                    # <<< PASSO 4: Atualizar o cérebro após cada trade >>>
                    pnl_do_trade = (sell_price / buy_price) - 1
                    confidence_manager.update(pnl_do_trade)

                    btc_amount, in_position, trade_executed_this_step = 0.0, False, 1
            
            else:
                # <<< PASSO 5: Usar a confiança dinâmica para tomar a decisão >>>
                current_confidence_threshold = confidence_manager.get_confidence()
                conviction = predictions_buy_proba.get(date, 0)

                if conviction > current_confidence_threshold:
                    signal_strength = (conviction - current_confidence_threshold) / (1.0 - current_confidence_threshold)
                    dynamic_risk_pct = base_risk_per_trade * (0.5 + signal_strength)
                    trade_size_usdt = capital * dynamic_risk_pct
                    
                    if capital > 10 and trade_size_usdt > 10:
                        buy_price_eff = price * (1 + SLIPPAGE_RATE)
                        amount_to_buy_btc = trade_size_usdt / buy_price_eff
                        fee = trade_size_usdt * FEE_RATE
                        
                        btc_amount = amount_to_buy_btc
                        capital -= (trade_size_usdt + fee)
                        buy_price, in_position, trade_executed_this_step = buy_price_eff, True, 1
            
            current_value = capital + (btc_amount * price)
            portfolio_history.append({'timestamp': date, 'value': current_value, 'trade_executed': trade_executed_this_step})

        self.generate_report(portfolio_history)