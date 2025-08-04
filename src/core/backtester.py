# Ficheiro: src/core/backtester.py (VERSÃO DE ALTA FIDELIDADE)

import pandas as pd
from tqdm import tqdm

from src.logger import logger
from src.config_manager import settings
from src.core.ensemble_manager import EnsembleManager
from src.core.position_manager import PositionManager

class Backtester:
    def __init__(self, data: pd.DataFrame, ensemble_manager: EnsembleManager, position_manager: PositionManager):
        self.data = data
        self.ensemble_manager = ensemble_manager
        self.position_manager = position_manager
        self.initial_capital = settings.backtest.initial_capital
        self.capital = self.initial_capital
        logger.info("Backtester de Alta Fidelidade inicializado.")

    def run(self):
        logger.info(f"Iniciando simulação com {len(self.data)} velas...")

        for timestamp, candle in tqdm(self.data.iterrows(), total=len(self.data), desc="Simulando Trades"):
            # 1. Gestão de Saídas é delegada ao PositionManager
            closed_trades = self.position_manager.check_and_close_positions(candle)
            for trade in closed_trades:
                # A lógica de capital aqui é uma simplificação para o backtest
                self.capital += trade.get('pnl_usd', 0)
                logger.info(f"[{timestamp}] Posição FECHADA ({trade['exit_reason']}). P&L: ${trade.get('pnl_usd', 0):.2f}. Capital: ${self.capital:,.2f}")

            # 2. Obtenção de Sinal é delegada ao EnsembleManager
            signal, confidence = self.ensemble_manager.get_ensemble_signal(candle)

            # 3. Decisão de Entrada é delegada ao PositionManager
            self.position_manager.check_for_entry(candle, signal, confidence)

        self.print_results()

    def print_results(self):
        pnl_total = self.capital - self.initial_capital
        pnl_percent = (pnl_total / self.initial_capital) * 100
        logger.info("--- 🏁 RESULTADOS DO BACKTEST (ESTRATEGA) 🏁 ---")
        logger.info(f"Capital Final: ${self.capital:,.2f}")
        logger.info(f"Lucro/Prejuízo Total: ${pnl_total:,.2f} ({pnl_percent:.2f}%)")