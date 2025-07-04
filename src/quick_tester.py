# src/quick_tester.py (VERSÃO 2.0 - COM ESTRATÉGIA COMPLETA E RELATÓRIO AVANÇADO)

import json
import pandas as pd
import numpy as np
import joblib
from tabulate import tabulate

from src.logger import logger
from src.config import MODEL_FILE, SCALER_FILE, STRATEGY_PARAMS_FILE, SYMBOL
from src.data_manager import DataManager
from src.model_trainer import ModelTrainer
from src.confidence_manager import AdaptiveConfidenceManager

# <<< PASSO 1: Definir as constantes da estratégia aqui também para consistência >>>
FEE_RATE = 0.001
SLIPPAGE_RATE = 0.0005
PARTIAL_SELL_PCT = 0.5
TREASURY_ALLOCATION_PCT = 0.20

class QuickTester:
    """
    Realiza um backtest de validação (out-of-sample) de um modelo treinado,
    simulando a ESTRATÉGIA MULTI-CAMADA COMPLETA para gerar
    um relatório de performance detalhado.
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

    def generate_report(self, portfolio_history: list, test_period_days: int):
        """Gera e imprime um relatório de performance mensal e geral."""
        if not portfolio_history:
            logger.warning("Histórico de portfólio vazio. Não é possível gerar relatório.")
            return

        df = pd.DataFrame(portfolio_history).set_index('timestamp')
        df['pnl'] = df['value'].diff()
        
        # --- Relatório Mensal (como estava antes) ---
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
        logger.info("--- RELATÓRIO DE PERFORMANCE MENSAL (OUT-OF-SAMPLE) ---")
        print(tabulate(report_data, headers='keys', tablefmt='pipe', showindex=False))
        
        # --- PASSO 2: Aprimorar o Resumo Geral com as novas métricas ---
        initial_capital = df['value'].iloc[0]
        final_capital = df['value'].iloc[-1]
        final_treasury_btc = df['treasury_btc'].iloc[-1]
        
        total_return = (final_capital / initial_capital) - 1
        annualized_return = ((1 + total_return) ** (365.0 / test_period_days)) - 1 if test_period_days > 0 else 0
        
        running_max = df['value'].cummax()
        drawdown = (df['value'] - running_max) / running_max
        max_drawdown = drawdown.min()
        
        calmar_ratio = annualized_return / abs(max_drawdown) if max_drawdown != 0 else 0
        
        total_trades = df['trade_executed'].sum()
        
        logger.info("\n" + "--- RESUMO GERAL DA PERFORMANCE ---")
        summary_data = [
            ["Período Testado", f"{df.index.min():%Y-%m-%d} a {df.index.max():%Y-%m-%d}"],
            ["Capital Inicial", f"${initial_capital:,.2f}"],
            ["Capital Final", f"${final_capital:,.2f}"],
            ["Resultado Total", f"{total_return:+.2%}"],
            ["Retorno Anualizado", f"{annualized_return:+.2%}"],
            ["Máximo Drawdown", f"{max_drawdown:.2%}"],
            ["Calmar Ratio", f"{calmar_ratio:.2f}"],
            ["Total de Trades", f"{int(total_trades)}"],
            ["Tesouro de BTC Acumulado", f"{final_treasury_btc:.8f} BTC"]
        ]
        print(tabulate(summary_data, tablefmt="fancy_grid"))
        logger.info("="*80)

    def run(self, start_date_str: str, end_date_str: str, initial_capital: float = 100.0):
        """Executa a simulação de backtest com a estratégia completa."""
        if not self.load_model_and_params():
            return

        logger.info(f"Carregando e preparando dados para o período de {start_date_str} a {end_date_str}...")
        full_data = self.data_manager.update_and_load_data(SYMBOL, '1m')
        
        test_data = full_data.loc[start_date_str:end_date_str]
        if test_data.empty:
            logger.error("Não há dados disponíveis para o período de teste solicitado.")
            return
        
        test_features = self.trainer._prepare_features(test_data.copy())
        if not hasattr(self.trainer, 'final_feature_names') or not self.trainer.final_feature_names:
             logger.error("A lista de features finais não foi inicializada. Execute o trainer primeiro.")
             return

        X_test_scaled = self.scaler.transform(test_features[self.trainer.final_feature_names])
        predictions_proba = self.model.predict_proba(X_test_scaled)
        predictions_buy_proba = pd.Series(predictions_proba[:, 1], index=test_features.index)

        # --- PASSO 3: Replicar a mesma lógica de estado do backtest.py ---
        capital = initial_capital
        long_term_btc_holdings = 0.0
        
        in_position = False
        buy_price = 0.0
        btc_amount = 0.0
        position_phase = None
        current_stop_price = 0.0
        highest_price_in_trade = 0.0

        portfolio_history = []
        
        base_risk = self.strategy_params.get('risk_per_trade_pct', 0.05)
        profit_th = self.strategy_params.get('profit_threshold', 0.04)
        stop_loss_th = self.strategy_params.get('stop_loss_threshold', 0.02)
        trailing_stop_pct = stop_loss_th * 1.5
        
        confidence_manager = AdaptiveConfidenceManager(
            initial_confidence=self.strategy_params.get('initial_confidence', 0.6),
            learning_rate=self.strategy_params.get('confidence_learning_rate', 0.05)
        )
        
        logger.info("Iniciando simulação de trading no período de teste...")
        for date, row in test_features.iterrows():
            price = row['close']
            trade_executed_this_step = 0
            
            # --- Lógica da Estratégia Multi-Camada (copiada do backtest.py para consistência) ---
            regime = row.get('market_regime', 'LATERAL')
            is_trading_allowed = True
            current_base_risk = base_risk

            if regime == 'BEAR': is_trading_allowed = False
            elif regime == 'RECUPERACAO': current_base_risk /= 2
            elif regime == 'LATERAL': current_base_risk /= 4

            if in_position:
                highest_price_in_trade = max(highest_price_in_trade, price)
                if price <= current_stop_price:
                    sell_price = price * (1 - SLIPPAGE_RATE)
                    capital += (btc_amount * sell_price) * (1 - FEE_RATE)
                    pnl = (sell_price / buy_price) - 1
                    confidence_manager.update(pnl)
                    in_position, btc_amount, trade_executed_this_step = False, 0.0, 1
                elif position_phase == 'INITIAL' and price >= buy_price * (1 + stop_loss_th):
                    position_phase = 'BREAKEVEN'
                    current_stop_price = buy_price * (1 + (FEE_RATE * 2))
                elif position_phase == 'BREAKEVEN' and price >= buy_price * (1 + profit_th):
                    amount_to_sell = btc_amount * PARTIAL_SELL_PCT
                    sell_price = price * (1 - SLIPPAGE_RATE)
                    revenue = (amount_to_sell * sell_price) * (1 - FEE_RATE)
                    profit_usdt = (sell_price - buy_price) * amount_to_sell
                    treasury_usdt = profit_usdt * TREASURY_ALLOCATION_PCT
                    long_term_btc_holdings += treasury_usdt / price
                    capital += revenue - treasury_usdt
                    btc_amount -= amount_to_sell
                    position_phase = 'TRAILING'
                    trade_executed_this_step = 1
                elif position_phase == 'TRAILING':
                    new_trailing_stop = highest_price_in_trade * (1 - trailing_stop_pct)
                    current_stop_price = max(current_stop_price, new_trailing_stop)

            if not in_position and is_trading_allowed:
                conviction = predictions_buy_proba.get(date, 0)
                if conviction > confidence_manager.get_confidence():
                    signal_strength = (conviction - confidence_manager.get_confidence()) / (1.0 - confidence_manager.get_confidence())
                    dynamic_risk_pct = current_base_risk * (0.5 + signal_strength)
                    trade_size_usdt = capital * dynamic_risk_pct
                    if capital > 10 and trade_size_usdt > 10:
                        buy_price_eff = price * (1 + SLIPPAGE_RATE)
                        amount_to_buy_btc = trade_size_usdt / buy_price_eff
                        fee = trade_size_usdt * FEE_RATE
                        in_position, btc_amount, capital = True, amount_to_buy_btc, capital - (trade_size_usdt + fee)
                        buy_price, current_stop_price, highest_price_in_trade = buy_price_eff, buy_price_eff * (1 - stop_loss_th), buy_price_eff
                        position_phase, trade_executed_this_step = 'INITIAL', 1
            
            current_value = capital + (btc_amount * price)
            portfolio_history.append({
                'timestamp': date, 
                'value': current_value, 
                'trade_executed': trade_executed_this_step,
                'treasury_btc': long_term_btc_holdings
            })
            
        test_period_days = (test_features.index[-1] - test_features.index[0]).days
        self.generate_report(portfolio_history, test_period_days)