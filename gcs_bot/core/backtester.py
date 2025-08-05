# Ficheiro: src/core/backtester.py (VERSÃO FINAL COM ESTRATEGA)

import pandas as pd
from tqdm import tqdm
from gcs_bot.core.position_manager import PositionManager

class Backtester:
    def __init__(self, data: pd.DataFrame, position_manager: PositionManager, config, logger):
        self.data = data
        self.position_manager = position_manager
        self.config = config
        self.logger = logger

        self.initial_capital = self.config.backtest.initial_capital
        self.commission_rate = self.config.backtest.commission_rate
        self.capital = self.initial_capital
        self.logger.info("Backtester inicializado com ESTRATEGA GRID-DCA.")

    def run(self):
        self.logger.info(f"Iniciando simulação com {len(self.data)} velas...")

        for timestamp, candle in tqdm(self.data.iterrows(), total=len(self.data), desc="Simulando Trades"):

            # 1. VERIFICAR SAÍDAS (LUCRO OU STOP-LOSS)
            closed_trades = self.position_manager.check_and_close_positions(candle)
            if closed_trades:
                for trade in closed_trades:
                    # O pnl já considera o preço de entrada e saída. A comissão é sobre o valor total da transação.
                    trade_value = trade['exit_price'] * trade['quantity_btc']
                    commission = trade_value * self.commission_rate
                    self.capital += trade['pnl_usdt'] - commission
                    self.logger.info(f"[{timestamp}] Posição FECHADA ({trade['exit_reason']}). P&L: ${trade['pnl_usdt']:.2f}. Capital: ${self.capital:,.2f}")

            # 2. DELEGAR A DECISÃO DE ENTRADA AO ESTRATEGA
            buy_decision = self.position_manager.check_for_entry(candle)

            # 3. EXECUTAR A COMPRA SE O ESTRATEGA DECIDIR
            if buy_decision:
                trade_size_usdt = self.position_manager.get_capital_per_trade(self.capital)

                # Garante que não vamos alocar mais capital do que temos
                if trade_size_usdt > self.capital:
                    self.logger.warning(f"Tamanho do trade ({trade_size_usdt:.2f}) excede o capital disponível ({self.capital:.2f}). Pulando trade.")
                    continue

                buy_decision['trade_size_usdt'] = trade_size_usdt

                # Abrir a posição (registra no DB)
                self.position_manager.open_position(candle, buy_decision)

                # Simular o custo e a comissão
                entry_price = candle['close']
                quantity_btc = trade_size_usdt / entry_price
                commission = trade_size_usdt * self.commission_rate
                self.capital -= (trade_size_usdt + commission)

                self.logger.info(f"[{timestamp}] Nova Posição ABERTA. Custo: ${trade_size_usdt:.2f}. Capital Restante: ${self.capital:,.2f}")

        self.print_results()

    def print_results(self):
        pnl_total = self.capital - self.initial_capital
        pnl_percent = (pnl_total / self.initial_capital) * 100
        self.logger.info("--- 🏁 RESULTADOS DO BACKTEST (ESTRATEGA GRID-DCA) 🏁 ---")
        self.logger.info(f"Capital Final: ${self.capital:,.2f}")
        self.logger.info(f"Lucro/Prejuízo Total: ${pnl_total:,.2f} ({pnl_percent:.2f}%)")