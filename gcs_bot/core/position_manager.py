# Ficheiro: src/core/position_manager.py (VERSÃO ESTRATEGA GRID-DCA)

import pandas as pd
import uuid
from datetime import datetime, timezone
import json
from typing import Optional

class PositionManager:
    def __init__(self, config, db_manager, logger, account_manager):
        self.config = config
        self.db_manager = db_manager
        self.logger = logger
        self.account_manager = account_manager

        self.position_config = self.config.position_management
        self.sizing_config = self.config.dynamic_sizing
        self.strategy_config = self.config.trading_strategy

        self.profit_target_mult = self.strategy_config.triple_barrier.profit_mult
        self.stop_loss_mult = self.strategy_config.triple_barrier.stop_mult
        
        # --- NOVOS PARÂMETROS ESTRATÉGICOS ---
        self.dca_grid_spacing_percent = self.strategy_config.dca_grid_spacing_percent / 100.0

        self.performance_factor = 1.0
        self.previous_candle = None

    def _update_performance_factor(self):
        if not self.sizing_config.enabled:
            self.performance_factor = 1.0
            return

        n_trades = self.sizing_config.performance_window_trades
        trades_df = self.db_manager.get_last_n_trades(n=n_trades)

        if trades_df.empty or len(trades_df) < n_trades:
            self.performance_factor = 1.0
            return

        gross_profit = trades_df[trades_df['pnl'] > 0]['pnl'].sum()
        gross_loss = abs(trades_df[trades_df['pnl'] < 0]['pnl'].sum())
        profit_factor = float('inf') if gross_loss == 0 else gross_profit / gross_loss

        self.logger.info(f"Análise de Performance: Últimos {len(trades_df)} trades. Profit Factor: {profit_factor:.2f}")

        if profit_factor > self.sizing_config.profit_factor_threshold:
            self.performance_factor = self.sizing_config.performance_upscale_factor
        else:
            self.performance_factor = self.sizing_config.performance_downscale_factor
            
    def get_capital_per_trade(self, available_capital: float) -> float:
        self._update_performance_factor()
        base_risk_percent = self.position_config.capital_per_trade_percent / 100
        dynamic_risk_percent = base_risk_percent * self.performance_factor
        trade_size_usdt = available_capital * min(dynamic_risk_percent, 0.10)
        return trade_size_usdt

    def open_position(self, candle: pd.Series, decision_data: dict = None):
        try:
            entry_price = candle['close']
            atr = candle['atr_14']
            if pd.isna(atr) or atr == 0: return

            profit_target_price = entry_price + (atr * self.profit_target_mult)
            stop_loss_price = entry_price - (atr * self.stop_loss_mult)
            quantity_btc = decision_data.get('trade_size_usdt', 0) / entry_price

            trade_data = {
                "trade_id": str(uuid.uuid4()), "status": "OPEN", "entry_price": entry_price,
                "quantity_btc": quantity_btc, "profit_target_price": profit_target_price,
                "stop_loss_price": stop_loss_price, "timestamp": datetime.now(timezone.utc),
                "decision_data": decision_data or {}
            }
            self.db_manager.write_trade(trade_data)
        except Exception as e:
            self.logger.error(f"Erro ao tentar abrir posição: {e}", exc_info=True)

    def check_and_close_positions(self, candle: pd.Series):
        closed_trades_summaries = []
        current_price = candle['close']
        open_positions_df = self.db_manager.get_open_positions()
        commission_rate = self.config.backtest.commission_rate
        trailing_config = self.config.trailing_profit

        if open_positions_df.empty:
            return []

        for trade_id, position in open_positions_df.iterrows():
            exit_reason = None

            # --- LÓGICA DE TRAILING PROFIT TARGET ---
            unrealized_pnl_percent = (current_price - position['entry_price']) / position['entry_price']
            if unrealized_pnl_percent >= (trailing_config.activation_percentage / 100.0):
                new_profit_target = current_price * (1 - (trailing_config.trailing_percentage / 100.0))
                if new_profit_target > position['profit_target_price']:
                    self.logger.info(f"🚀 ATUALIZANDO PROFIT TARGET PARA O TRADE {trade_id}:")
                    self.logger.info(f"   Antigo Alvo: ${position['profit_target_price']:,.2f}")
                    self.logger.info(f"   Novo Alvo:   ${new_profit_target:,.2f}")
                    # Atualiza o trade no DB
                    self.db_manager.write_trade({
                        "trade_id": trade_id,
                        "status": "OPEN", # Mantém o status OPEN
                        "profit_target_price": new_profit_target,
                        "timestamp": datetime.now(timezone.utc)
                    })
                    # Atualiza a posição no DF local para o resto da lógica
                    position['profit_target_price'] = new_profit_target

            # Calcula o PnL líquido, considerando as comissões de entrada e saída
            entry_cost = position['entry_price'] * position['quantity_btc']
            exit_value = current_price * position['quantity_btc']
            commission_entry = entry_cost * commission_rate
            commission_exit = exit_value * commission_rate
            net_pnl = exit_value - entry_cost - commission_entry - commission_exit

            # Condição de Take Profit: só executa se o lucro líquido for maior que o mínimo configurado
            if current_price >= position['profit_target_price']:
                if net_pnl > self.config.trading_strategy.minimum_profit_for_take_profit:
                    exit_reason = 'TAKE_PROFIT'
                else:
                    self.logger.debug(f"TAKE PROFIT para o trade {trade_id} ignorado. Lucro líquido ({net_pnl:.2f}) não atinge o mínimo de {self.config.trading_strategy.minimum_profit_for_take_profit}.")

            # Condição de Stop Loss: removida

            if exit_reason:
                self.logger.info(f"✅ FECHANDO TRADE {trade_id} POR {exit_reason}:")
                self.logger.info(f"   Preço de Entrada: ${position['entry_price']:,.2f}")
                self.logger.info(f"   Preço de Saída:   ${current_price:,.2f}")
                self.logger.info(f"   Quantidade:       {position['quantity_btc']:.8f} BTC")
                self.logger.info(f"   Comissões:        ${(commission_entry + commission_exit):,.4f}")
                self.logger.info(f"   Resultado Líquido: ${net_pnl:,.2f}")

                close_trade_data = {
                    "trade_id": trade_id,
                    "status": "CLOSED",
                    "entry_price": position['entry_price'],
                    "realized_pnl_usdt": net_pnl,
                    "timestamp": datetime.now(timezone.utc),
                    "decision_data": {"exit_reason": exit_reason, "commission": commission_entry + commission_exit, "exit_price": current_price}
                }
                self.db_manager.write_trade(close_trade_data)
                summary = {
                    'entry_price': position['entry_price'],
                    'exit_price': current_price,
                    'quantity_btc': position['quantity_btc'],
                    'pnl_usdt': net_pnl,
                    'exit_reason': exit_reason
                }
                closed_trades_summaries.append(summary)
        return closed_trades_summaries

    def get_open_positions(self) -> pd.DataFrame:
        """Retorna um DataFrame com as posições abertas."""
        return self.db_manager.get_open_positions()

    def check_for_entry(self, candle: pd.Series) -> Optional[dict]:
        """
        Nova lógica de entrada estratégica AI-less, com verificação de fundos.
        Retorna um dicionário de decisão se uma compra deve ser executada, caso contrário None.
        """
        open_positions = self.get_open_positions()
        open_trades_count = len(open_positions)
        max_trades = self.position_config.max_concurrent_trades

        if open_trades_count >= max_trades:
            return None

        # Lógica de decisão de entrada (a mesma de antes)
        entry_decision = None
        if open_trades_count == 0:
            if self.previous_candle is not None and candle['close'] < self.previous_candle['close']:
                self.logger.info("ESTRATÉGIA 'ENTRAR NO JOGO': Primeira vela de baixa detectada.")
                entry_decision = {"reason": "FIRST_ENTRY_DIP"}
        elif open_trades_count > 0:
            average_entry_price = open_positions['entry_price'].mean()
            price_change_percent = (candle['close'] - average_entry_price) / average_entry_price
            if price_change_percent <= self.dca_grid_spacing_percent:
                self.logger.info(f"ESTRATÉGIA 'COMPRAR NA BAIXA': Preço caiu {price_change_percent:.2%}")
                entry_decision = {"reason": "DCA_GRID_ENTRY"}

        # Se não há decisão de entrada, atualiza e sai
        if not entry_decision:
            self.previous_candle = candle
            return None

        # --- VERIFICAÇÃO DE FUNDOS ---
        available_balance = self.account_manager.get_quote_asset_balance()
        required_capital = self.get_capital_per_trade(available_balance)

        # Adiciona uma margem de segurança (ex: 1%) para evitar problemas com ordens de mercado
        required_capital_with_slippage = required_capital * 1.01

        if available_balance < required_capital_with_slippage:
            self.logger.warning(f"ENTRADA IGNORADA: Saldo insuficiente. Saldo disponível: {available_balance:.2f} USDT, Capital necessário: {required_capital_with_slippage:.2f} USDT.")
            self.previous_candle = candle
            return None

        self.logger.info(f"Decisão de COMPRA confirmada com saldo suficiente. Alocando {required_capital:.2f} USDT.")
        # Adiciona o tamanho do trade na decisão para ser usado em open_position
        entry_decision['trade_size_usdt'] = required_capital

        self.previous_candle = candle
        return entry_decision