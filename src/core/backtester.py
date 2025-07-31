# src/core/backtester.py (NOVA VERSÃO PARA FASE 2)

import pandas as pd
from tqdm import tqdm
import plotly.graph_objects as go
from src.logger import logger
from src.config_manager import settings
# O Backtester agora importa o TradingBot inteiro, pois vai simulá-lo
from src.core.trading_bot import TradingBot 

class Backtester:
    def __init__(self, data: pd.DataFrame):
        self.data = data
        self.initial_capital = settings.backtest.initial_capital
        self.commission_rate = settings.backtest.commission_rate

        # O Backtester agora cria uma instância do próprio TradingBot!
        # Isto garante que estamos a testar o código EXATO que irá para produção.
        self.bot = TradingBot()

        # Inicializamos o portfólio virtual do bot com o capital inicial do backtest
        self.bot.portfolio.trading_capital_usdt = self.initial_capital
        self.bot.portfolio.trading_btc_balance = 0.0

        self.results = []
        self.equity_curve = []

    def run(self):
        """
        Executa o backtest, iterando por cada vela (timestamp) dos dados históricos.
        """
        logger.info(f"Iniciando backtest com Capital Inicial de ${self.initial_capital:,.2f}")

        # Usamos o tqdm para ter uma barra de progresso
        for index, candle in tqdm(self.data.iterrows(), total=len(self.data), desc="Executando Backtest"):

            # --- LÓGICA DE SIMULAÇÃO CENTRAL ---
            # O Backtester já não toma decisões. Ele apenas orquestra a simulação.

            # 1. Simular verificação de saídas
            closed_trades = self.bot.position_manager.check_and_close_positions(candle)
            if closed_trades:
                for trade_summary in closed_trades:
                    self._simulate_sell(trade_summary)

            # 2. Simular verificação de entradas
            max_trades = self.bot.position_config.max_concurrent_trades
            if self.bot.position_manager.get_open_positions_count() < max_trades:
                # Precisamos simular a lógica de _check_for_entry_signal aqui
                # Por enquanto, vamos simplificar e chamar um método de decisão.
                # No futuro, o bot.run() poderia ter um modo "backtest".
                self._simulate_entry_decision(candle)

            # 3. Registrar o valor do portfólio a cada passo
            current_price = candle['close']
            equity = self.bot.portfolio.get_total_portfolio_value_usdt(current_price)
            self.equity_curve.append({'timestamp': index, 'equity': equity})

        logger.info("Backtest concluído. Gerando relatório de performance...")
        self.generate_performance_report()

    def _simulate_entry_decision(self, candle):
        """
        Simula a lógica de decisão de entrada do TradingBot.
        """
        # Esta é uma versão simplificada do _check_for_entry_signal
        # No futuro, podemos refatorar o TradingBot para expor um método de "decisão".

        # AQUI VAI A LÓGICA DE SINAL (ainda usando um sinal simples por enquanto)
        # Vamos assumir que temos um sinal de compra para testar a mecânica
        # if self.bot.some_entry_logic(candle): # Placeholder

        # Para o teste, vamos criar uma lógica de sinal simples:
        # Comprar se o RSI estiver abaixo de 30 (exemplo)
        if 'rsi_14' in candle and candle['rsi_14'] < 30:
            available_capital = self.bot.portfolio.trading_capital_usdt
            trade_size_usdt = self.bot.position_manager.get_capital_per_trade(available_capital)

            if trade_size_usdt > 10:
                qty_to_buy = trade_size_usdt / candle['close']
                # Abre a posição no gestor
                self.bot.position_manager.open_position(candle['close'], qty_to_buy)
                # Simula a execução da compra
                self._simulate_buy(trade_size_usdt, qty_to_buy)

    def _simulate_buy(self, cost_usdt: float, quantity_btc: float):
        """Simula a execução de uma compra, atualizando o portfólio virtual."""
        commission = cost_usdt * self.commission_rate
        self.bot.portfolio.trading_capital_usdt -= (cost_usdt + commission)
        self.bot.portfolio.trading_btc_balance += quantity_btc
        logger.debug(f"COMPRA SIMULADA: {quantity_btc:.6f} BTC por ${cost_usdt:,.2f}")

    def _simulate_sell(self, trade_summary: dict):
        """Simula a execução de uma venda, atualizando o portfólio virtual."""
        revenue = trade_summary['exit_price'] * trade_summary['quantity_btc']
        commission = revenue * self.commission_rate
        self.bot.portfolio.trading_capital_usdt += (revenue - commission)
        self.bot.portfolio.trading_btc_balance -= trade_summary['quantity_btc']

        # Registramos o resultado do trade
        self.results.append(trade_summary)
        logger.debug(f"VENDA SIMULADA: {trade_summary['quantity_btc']:.6f} BTC. P&L: ${trade_summary['pnl_usdt']:,.2f}")

    def generate_performance_report(self):
        """Calcula e imprime as métricas de performance do backtest."""
        if not self.results:
            logger.warning("Nenhum trade foi executado no backtest. Não é possível gerar relatório.")
            return

        df_results = pd.DataFrame(self.results)
        total_trades = len(df_results)
        wins = df_results[df_results['pnl_usdt'] > 0]
        losses = df_results[df_results['pnl_usdt'] <= 0]

        win_rate = (len(wins) / total_trades) * 100 if total_trades > 0 else 0
        gross_profit = wins['pnl_usdt'].sum()
        gross_loss = abs(losses['pnl_usdt'].sum())
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')

        final_equity = self.equity_curve[-1]['equity']
        total_return = ((final_equity / self.initial_capital) - 1) * 100

        print("\n--- 📊 Relatório de Performance do Backtest 📊 ---")
        print(f" Período Analisado: {self.data.index.min().date()} a {self.data.index.max().date()}")
        print("-" * 50)
        print(f" Resultado Final do Portfólio: ${final_equity:,.2f}")
        print(f" Retorno Total: {total_return:.2f}%")
        print(f" Total de Trades: {total_trades}")
        print(f" Taxa de Acerto: {win_rate:.2f}%")
        print(f" Profit Factor: {profit_factor:.2f}")
        print(f" Lucro Bruto: ${gross_profit:,.2f}")
        print(f" Perda Bruta: ${gross_loss:,.2f}")
        print("-" * 50)

        df_equity = pd.DataFrame(self.equity_curve).set_index('timestamp')
        fig = go.Figure(data=go.Scatter(x=df_equity.index, y=df_equity['equity'], name='Patrimônio'))
        fig.update_layout(title='Curva de Patrimônio do Backtest', xaxis_title='Data', yaxis_title='Valor do Portfólio (USDT)')
        fig.show()