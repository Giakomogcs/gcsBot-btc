# src/core/backtester.py (VERSÃO FINAL COM IA)

import pandas as pd
from tqdm import tqdm
import plotly.graph_objects as go
from src.logger import logger
from src.config_manager import settings
from src.core.trading_bot import TradingBot
from src.core.ensemble_manager import EnsembleManager # Importar

class Backtester:
    def __init__(self, data: pd.DataFrame, ensemble_manager: EnsembleManager):
        self.data = data
        self.initial_capital = settings.backtest.initial_capital
        self.commission_rate = settings.backtest.commission_rate
        
        self.bot = TradingBot(initial_capital_for_backtest=self.initial_capital)
        
        # O backtester agora tem o cérebro (ensemble) à sua disposição
        self.ensemble_manager = ensemble_manager
        
        self.results = []
        self.equity_curve = []

    def run(self):
        logger.info(f"Iniciando backtest com IA. Capital Inicial de ${self.initial_capital:,.2f}")
        
        for index, candle in tqdm(self.data.iterrows(), total=len(self.data), desc="Backtesting com IA"):
            
            closed_trades = self.bot.position_manager.check_and_close_positions(candle)
            if closed_trades:
                for trade_summary in closed_trades:
                    self._simulate_sell(trade_summary)

            max_trades = self.bot.position_config.max_concurrent_trades
            if self.bot.position_manager.get_open_positions_count() < max_trades:
                self._simulate_entry_decision_with_ai(candle)

            current_price = candle['close']
            equity = self.bot.portfolio.get_total_portfolio_value_usdt(current_price)
            self.equity_curve.append({'timestamp': index, 'equity': equity})

        logger.info("Backtest concluído. Gerando relatório de performance...")
        self.generate_performance_report()

    def _simulate_entry_decision_with_ai(self, candle):
        """
        Usa o EnsembleManager para obter uma predição e decidir sobre a entrada.
        """
        # Obtém a predição real da IA
        confidence, details = self.ensemble_manager.get_prediction(candle)
        signal = details.get('signal')
        
        # Entra se o sinal for de compra (LONG) e a confiança exceder o limiar
        if signal == 'LONG' and confidence > settings.trading_strategy.confidence_threshold:
            available_capital = self.bot.portfolio.trading_capital_usdt
            trade_size_usdt = self.bot.position_manager.get_capital_per_trade(available_capital)
            
            if trade_size_usdt > 10 and available_capital >= trade_size_usdt:
                qty_to_buy = trade_size_usdt / candle['close']
                self.bot.position_manager.open_position(candle['close'], qty_to_buy)
                self._simulate_buy(trade_size_usdt, qty_to_buy)

    def _simulate_buy(self, cost_usdt: float, quantity_btc: float):
        commission = cost_usdt * self.commission_rate
        self.bot.portfolio.update_on_buy(cost_usdt + commission, quantity_btc)

    def _simulate_sell(self, trade_summary: dict):
        revenue = trade_summary['exit_price'] * trade_summary['quantity_btc']
        commission = revenue * self.commission_rate
        self.bot.portfolio.update_on_sell(revenue - commission, trade_summary['quantity_btc'])
        self.results.append(trade_summary)

    def generate_performance_report(self):
        # ... (esta função permanece igual à versão anterior)
        if not self.results:
            logger.warning("Nenhum trade foi executado no backtest.")
            return

        df_results = pd.DataFrame(self.results)
        total_trades = len(df_results)
        wins = df_results[df_results['pnl_usdt'] > 0]
        win_rate = (len(wins) / total_trades) * 100 if total_trades > 0 else 0
        gross_profit = wins['pnl_usdt'].sum()
        gross_loss = abs(df_results[df_results['pnl_usdt'] <= 0]['pnl_usdt'].sum())
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')
        
        final_equity = self.equity_curve[-1]['equity']
        total_return = ((final_equity / self.initial_capital) - 1) * 100

        print("\n--- 📊 Relatório de Performance do Backtest (IA) 📊 ---")
        print(f"Resultado Final: ${final_equity:,.2f} | Retorno: {total_return:.2f}%")
        print(f"Trades: {total_trades} | Acerto: {win_rate:.2f}% | Profit Factor: {profit_factor:.2f}")
        print("-" * 50)

        df_equity = pd.DataFrame(self.equity_curve).set_index('timestamp')
        fig = go.Figure(data=go.Scatter(x=df_equity.index, y=df_equity['equity'], name='Patrimônio'))
        fig.update_layout(title='Curva de Patrimônio do Backtest', xaxis_title='Data', yaxis_title='Valor do Portfólio (USDT)')
        fig.show()