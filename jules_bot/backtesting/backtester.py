# Ficheiro: src/core/backtester.py (VERSÃO FINAL COM ESTRATEGA)

import pandas as pd
from tqdm import tqdm
from jules_bot.bot.position_manager import PositionManager


class Backtester:
    def __init__(self, data: pd.DataFrame, position_manager: PositionManager, config, logger):
        self.data = data
        self.position_manager = position_manager
        self.config = config
        self.logger = logger

        self.initial_capital = self.config.backtest.initial_capital
        self.commission_rate = self.config.backtest.commission_rate
        self.capital = self.initial_capital
        self.btc_treasury = 0.0 
        self.logger.info("Backtester inicializado com ESTRATEGA GRID-DCA.")

    def run(self):
        self.logger.info(f"Iniciando simulação com {len(self.data)} velas...")

        for timestamp, candle in tqdm(self.data.iterrows(), total=len(self.data), desc="Simulando Trades"):

           # 1. VERIFICAR SAÍDAS (LUCRO OU STOP-LOSS)
            closed_trades = self.position_manager.check_and_close_positions(candle)
            if closed_trades:
                for trade in closed_trades:
                    # Adiciona o lucro líquido da venda ao capital em USDT
                    self.capital += trade['pnl_usdt']
                    
                    # ADICIONA O BTC RESTANTE AO TESOURO
                    self.btc_treasury += trade['quantity_btc_remaining']

                    self.logger.info(f"[{timestamp}] Posição FECHADA PARCIALMENTE. P&L Realizado: ${trade['pnl_usdt']:.2f}. Capital: ${self.capital:,.2f}")
                    self.logger.info(f"    -> {trade['quantity_btc_remaining']:.8f} BTC movidos para o tesouro. Tesouro total: {self.btc_treasury:.8f} BTC")
                
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
        """
        Calcula e imprime os resultados finais usando o tesouro de BTC
        controlado internamente pelo Backtester.
        """
        self.logger.info("--- 🏁 RESULTADOS DO BACKTEST (ESTRATEGA GRID-DCA) 🏁 ---")
        
        # Usa o tesouro de BTC mantido em memória, que é a fonte mais confiável.
        final_btc_balance = self.btc_treasury
        
        # O resto dos cálculos permanece o mesmo
        final_price = self.data.iloc[-1]['close']
        final_btc_value_usdt = final_btc_balance * final_price
        final_total_portfolio_value = self.capital + final_btc_value_usdt
        pnl_total = final_total_portfolio_value - self.initial_capital
        pnl_percent = (pnl_total / self.initial_capital) * 100 if self.initial_capital > 0 else 0

        # Imprimir o relatório de portfólio
        self.logger.info(f"Período Analisado: {self.data.index.min().date()} a {self.data.index.max().date()}")
        self.logger.info("-" * 55)
        self.logger.info(f"Capital Inicial: ................... ${self.initial_capital:,.2f} USDT")
        self.logger.info(f"Capital Final (em USDT): ........... ${self.capital:,.2f} USDT")
        self.logger.info(f"Tesouro Acumulado ('Guardado'): .... {final_btc_balance:.8f} BTC")
        self.logger.info(f"Valor do Tesouro Acumulado: ....... + ${final_btc_value_usdt:,.2f} USDT")
        self.logger.info("=" * 55)
        self.logger.info(f"VALOR TOTAL FINAL DO PORTFÓLIO: .. ${final_total_portfolio_value:,.2f} USDT")
        self.logger.info(f"LUCRO/PREJUÍZO TOTAL (P&L): ...... ${pnl_total:,.2f} USDT ({pnl_percent:+.2f}%)")
        self.logger.info("-" * 55)
        
        # As estatísticas de win/loss ainda podem usar o DB como um log de operações
        db_manager = self.position_manager.db_manager
        all_trades = db_manager.get_all_trades_in_range(
            start_date=self.data.index.min().isoformat(),
            end_date=self.data.index.max().isoformat()
        )
        if not all_trades.empty:
            managed_trades = all_trades[all_trades['total_realized_pnl_usdt'] != 0].copy()
            if not managed_trades.empty:
                wins = managed_trades[managed_trades['total_realized_pnl_usdt'] > 0]
                losses = managed_trades[managed_trades['total_realized_pnl_usdt'] <= 0]
                win_rate = (len(wins) / len(managed_trades)) * 100 if not managed_trades.empty else 0
                
                self.logger.info(f"Total de Operações com P&L Realizado: {len(managed_trades)}")
                self.logger.info(f"Operações Vencedoras: ............ {len(wins)}")
                self.logger.info(f"Operações Perdedoras: ............ {len(losses)}")
                self.logger.info(f"Taxa de Acerto (Win Rate): ........ {win_rate:.2f}%")
            else:
                self.logger.info("Nenhuma operação com P&L foi realizada no período.")
        
        self.logger.info("-" * 55)