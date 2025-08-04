# Ficheiro: src/core/backtester.py (VERSÃO FINAL COM ESTRATEGA)

import pandas as pd
from tqdm import tqdm

from gcs_bot.utils.logger import logger
from gcs_bot.utils.config_manager import settings
from gcs_bot.core.ensemble_manager import EnsembleManager
from gcs_bot.core.position_manager import PositionManager

class Backtester:
    def __init__(self, data: pd.DataFrame, ensemble_manager: EnsembleManager, position_manager: PositionManager):
        self.data = data
        self.ensemble_manager = ensemble_manager
        self.position_manager = position_manager
        self.initial_capital = settings.backtest.initial_capital
        self.commission_rate = settings.backtest.commission_rate
        self.capital = self.initial_capital
        logger.info("Backtester inicializado com ESTRATEGA GRID-DCA.")

    def run(self):
        logger.info(f"Iniciando simulação com {len(self.data)} velas...")

        for timestamp, candle in tqdm(self.data.iterrows(), total=len(self.data), desc="Simulando Trades"):
            
            # 1. VERIFICAR SAÍDAS (LUCRO OU STOP-LOSS)
            closed_trades = self.position_manager.check_and_close_positions(candle)
            if closed_trades:
                for trade in closed_trades:
                    self.capital += trade['pnl_usdt'] - (trade['exit_price'] * trade['quantity_btc'] * self.commission_rate)
                    logger.info(f"[{timestamp}] Posição FECHADA ({trade['exit_reason']}). P&L: ${trade['pnl_usdt']:.2f}. Capital: ${self.capital:,.2f}")

            # 2. OBTER SINAL DA IA (MAS A DECISÃO FINAL É DO ESTRATEGA)
            signal, decision_report = self.ensemble_manager.get_ensemble_signal(candle)

            # 3. DELEGAR A DECISÃO DE ENTRADA AO ESTRATEGA
            # Guardamos o estado do capital antes de uma possível compra
            capital_before_trade = self.capital
            
            # O Position Manager agora contém a lógica de quando comprar
            self.position_manager.check_for_entry(candle, signal, decision_report)
            
            # A lógica de 'execute_buy' é simulada aqui no backtester
            # Se uma nova posição foi aberta, o número de trades no DB aumentou.
            open_positions_after = self.position_manager.get_open_positions()
            
            # Lógica para simular o capital se uma nova posição foi aberta nesta vela
            # Esta é uma simplificação; uma versão mais robusta teria um sistema de eventos.
            if len(open_positions_after) > len(closed_trades): # Detecta se uma nova posição foi aberta
                last_trade_db = open_positions_after.iloc[-1]
                # Simula o custo da última posição aberta
                trade_cost = last_trade_db['entry_price'] * last_trade_db['quantity_btc']
                self.capital -= trade_cost * self.commission_rate
                logger.info(f"[{timestamp}] Nova Posição ABERTA registrada. Capital atual: ${self.capital:,.2f}")


        self.print_results()
        
    def print_results(self):
        pnl_total = self.capital - self.initial_capital
        pnl_percent = (pnl_total / self.initial_capital) * 100
        logger.info("--- 🏁 RESULTADOS DO BACKTEST (ESTRATEGA GRID-DCA) 🏁 ---")
        logger.info(f"Capital Final: ${self.capital:,.2f}")
        logger.info(f"Lucro/Prejuízo Total: ${pnl_total:,.2f} ({pnl_percent:.2f}%)")