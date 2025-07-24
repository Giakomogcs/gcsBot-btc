# src/core/backtester.py

import pandas as pd
import numpy as np
from tqdm import tqdm
import matplotlib.pyplot as plt
from src.config_manager import settings
from src.core.position_sizer import DynamicPositionSizer


# Resolução de Path
import sys, os
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.core.ensemble_manager import EnsembleManager
from src.logger import logger

class Backtester:
    """
    Um motor de backtesting de nível profissional, baseado em eventos,
    que simula a performance de uma estratégia no passado.
    """
    def __init__(self, data: pd.DataFrame, ensemble: EnsembleManager):
        
        self.data = data
        self.ensemble = ensemble
        self.trades = []
        self.active_trade = None

        # --- USA AS CONFIGURAÇÕES CENTRALIZADAS ---
        self.commission_rate = settings.backtest.commission_rate
        self.initial_capital = settings.backtest.initial_capital
        self.future_periods = settings.backtest.future_periods
        self.profit_mult = settings.backtest.profit_mult
        self.stop_mult = settings.backtest.stop_mult
        
        
        self.position_sizer = DynamicPositionSizer()
        self.equity = self.initial_capital # O capital que cresce ou diminui

    def _plot_equity_curve(self, results_df: pd.DataFrame):
        """Plota a curva de capital ao longo do tempo."""
        plt.figure(figsize=(12, 6))
        plt.plot(results_df['exit_time'], results_df['equity_curve'])
        plt.title('Curva de Capital da Estratégia')
        plt.xlabel('Data')
        plt.ylabel('Crescimento do Capital (Inicial = 1.0)')
        plt.grid(True)
        # Salva o gráfico num ficheiro em vez de o mostrar
        plot_path = os.path.join(settings.data_paths.data_dir, 'equity_curve.png')
        plt.savefig(plot_path)
        logger.info(f"📈 Gráfico da curva de capital salvo em: {plot_path}")

    def _check_exit_conditions(self, current_index):
        """Verifica se uma posição ativa deve ser fechada."""
        if not self.active_trade:
            return

        trade_entry_index = self.active_trade['entry_index']
        time_elapsed = current_index - trade_entry_index
        
        # 1. Verifica se o tempo máximo do trade foi atingido
        if time_elapsed >= self.future_periods:
            self._close_trade(current_index, "Time Limit")
            return

        # 2. Verifica as barreiras de lucro e prejuízo
        high_since_entry = self.data['high'].iloc[trade_entry_index:current_index + 1].max()
        low_since_entry = self.data['low'].iloc[trade_entry_index:current_index + 1].min()

        if high_since_entry >= self.active_trade['profit_barrier']:
            self._close_trade(current_index, "Take Profit")
        elif low_since_entry <= self.active_trade['stop_barrier']:
            self._close_trade(current_index, "Stop Loss")

    def _open_trade(self, current_index):
        """Abre uma nova posição de compra usando o dimensionamento dinâmico."""
        entry_price = self.data['close'].iloc[current_index]
        atr = self.data['atr'].iloc[current_index]
        
        # --- LÓGICA DE DIMENSIONAMENTO DINÂMICO ---
        signal, confidence = self.ensemble.get_consensus_signal(self.data.iloc[[current_index]])
        
        # Se o sinal não for de compra, não faz nada
        if signal != 1:
            return

        trade_amount_usdt = self.position_sizer.calculate_trade_size(
            current_equity=self.equity,
            atr=atr,
            confidence_score=confidence
        )
        
        # Se o sizer decidir que o trade é muito pequeno ou arriscado, não abre
        if trade_amount_usdt <= 0:
            return
        
        # Abre o trade
        self.active_trade = {
            "entry_index": current_index,
            "entry_time": self.data.index[current_index],
            "entry_price": entry_price,
            "trade_amount_usdt": trade_amount_usdt, # Armazena o valor do trade
            "profit_barrier": entry_price + (atr * self.profit_mult),
            "stop_barrier": entry_price - (atr * self.stop_mult),
        }
        logger.debug(f"Trade Aberto em {self.data.index[current_index]} | Preço: {entry_price:.2f} | Tamanho: {trade_amount_usdt:.2f} USDT")

    def _close_trade(self, current_index, reason: str):
        """Fecha a posição ativa, regista o resultado e atualiza o capital."""
        exit_price = self.data['close'].iloc[current_index]
        entry_price = self.active_trade['entry_price']
        
        pnl_percent = (exit_price / entry_price) - 1
        commission = self.commission_rate * 2
        net_pnl_percent = pnl_percent - commission

        # Atualiza o capital
        pnl_amount = self.active_trade['trade_amount_usdt'] * net_pnl_percent
        self.equity += pnl_amount

        self.trades.append({
            **self.active_trade,
            "exit_time": self.data.index[current_index],
            "exit_price": exit_price,
            "exit_reason": reason,
            "pnl_percent": net_pnl_percent,
            "pnl_amount_usdt": pnl_amount # Regista o PnL em USDT
        })
        
        for specialist_name in self.ensemble.specialists.keys():
             self.ensemble.update_performance(specialist_name, net_pnl_percent)

        self.active_trade = None

    def _print_results(self):
        """Calcula, imprime e plota as métricas finais de performance."""
        if not self.trades:
            logger.warning("Nenhum trade foi executado durante o backtest.")
            return

        results_df = pd.DataFrame(self.trades)
        
        # --- A CORREÇÃO CRÍTICA ESTÁ AQUI ---
        # Calcula o fator de crescimento para cada trade e depois a curva de capital cumulativa
        results_df['growth_factor'] = 1 + results_df['pnl_percent']
        results_df['equity_curve'] = results_df['growth_factor'].cumprod()
        # --- FIM DA CORREÇÃO ---

        # Calcula as métricas de performance
        total_trades = len(results_df)
        wins = results_df[results_df['pnl_percent'] > 0]
        num_wins = len(wins)
        num_losses = total_trades - num_wins
        win_rate = (num_wins / total_trades * 100) if total_trades > 0 else 0
        
        total_pnl = results_df['equity_curve'].iloc[-1] - 1
        average_pnl = results_df['pnl_percent'].mean()
        average_win = wins['pnl_percent'].mean()
        average_loss = results_df[results_df['pnl_percent'] <= 0]['pnl_percent'].mean()
        
        risk_reward_ratio = abs(average_win / average_loss) if average_loss != 0 else float('inf')

        print("\n--- 📊 RESULTADOS DO BACKTEST 📊 ---")
        print(f" Período Analisado: {self.data.index.min()} a {self.data.index.max()}")
        print("------------------------------------")
        print(f" Trades Totais: {total_trades}")
        print(f" Vitórias: {num_wins}")
        print(f" Derrotas: {num_losses}")
        print(f" Taxa de Acerto: {win_rate:.2f}%")
        print("------------------------------------")
        print(f" Lucro Total: {total_pnl:+.2%}")
        print(f" Média por Trade: {average_pnl:+.4%}")
        print(f" Média das Vitórias: {average_win:+.4%}")
        print(f" Média das Derrotas: {average_loss:+.4%}")
        print(f" Rácio Risco/Recompensa: {risk_reward_ratio:.2f}")
        print("------------------------------------")
        
        # Chama a função de plot, que agora irá funcionar
        self._plot_equity_curve(results_df)

    def run(self):
        """Executa o loop principal do backtest."""
        logger.info("🚀 Iniciando Backtest Profissional...")
        
        for i in tqdm(range(len(self.data)), desc="Simulando Trades"):
            # 1. Verifica se um trade ativo deve ser fechado
            self._check_exit_conditions(i)

            # 2. Se não houver trade ativo, verifica se deve abrir um novo
            if not self.active_trade:
                current_candle_features = self.data.iloc[[i]]
                signal, _ = self.ensemble.get_consensus_signal(current_candle_features)
                if signal == 1:
                    self._open_trade(i)
        
        self._print_results()