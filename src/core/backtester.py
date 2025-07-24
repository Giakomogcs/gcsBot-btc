# src/core/backtester.py

import pandas as pd
import numpy as np
from tqdm import tqdm
import matplotlib.pyplot as plt
from config_manager import settings


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

        # --- Parâmetros de Backtest (deveriam vir do config.yml) ---
        self.commission_rate = 0.001 # 0.1% por transação
        self.initial_capital = 10000 # Começar com 10,000 USDT
        self.trade_amount = 1000 # Investir 1,000 USDT por trade
        self.future_periods = 30
        self.profit_mult = 2.0
        self.stop_mult = 2.0

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
        """Abre uma nova posição de compra."""
        entry_price = self.data['close'].iloc[current_index]
        atr = self.data['atr'].iloc[current_index]
        
        self.active_trade = {
            "entry_index": current_index,
            "entry_time": self.data.index[current_index],
            "entry_price": entry_price,
            "profit_barrier": entry_price + (atr * self.profit_mult),
            "stop_barrier": entry_price - (atr * self.stop_mult),
        }

    def _close_trade(self, current_index, reason: str):
        """Fecha a posição ativa e regista o resultado."""
        exit_price = self.data['close'].iloc[current_index]
        entry_price = self.active_trade['entry_price']
        
        pnl_percent = (exit_price / entry_price) - 1
        commission = self.commission_rate * 2 # Comissão na entrada e na saída
        net_pnl_percent = pnl_percent - commission

        self.trades.append({
            **self.active_trade,
            "exit_time": self.data.index[current_index],
            "exit_price": exit_price,
            "exit_reason": reason,
            "pnl_percent": net_pnl_percent
        })
        
        # Informa o Maestro sobre o resultado do trade
        # (Por enquanto, de forma simplificada)
        for specialist_name in self.ensemble.specialists.keys():
             self.ensemble.update_performance(specialist_name, net_pnl_percent)

        self.active_trade = None

    def _print_results(self):
        """Calcula, imprime e plota as métricas finais de performance."""
        if not self.trades:
            logger.warning("Nenhum trade foi executado durante o backtest.")
            return

        results_df = pd.DataFrame(self.trades)
        # ... (cálculos continuam iguais) ...
        
        print("\n--- 📊 RESULTADOS DO BACKTEST 📊 ---")
        # ... (prints continuam iguais) ...
        print("------------------------------------")
        
        # Chama a nova função de plot
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