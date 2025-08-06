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
        self.partial_sell_percent = self.strategy_config.partial_sell_percent / 100.0
        self.consecutive_green_candles_for_entry = self.strategy_config.consecutive_green_candles_for_entry

        self.performance_factor = 1.0
        self.previous_candle = None
        self.consecutive_green_candles = 0

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
        trade_size_usdt = decision_data.get('trade_size_usdt', 0)
        if trade_size_usdt <= 0:
            self.logger.warning("Tamanho de trade inválido para abrir posição. Abortando.")
            return

        # 1. Executar a ordem de compra primeiro
        buy_successful = self.account_manager.update_on_buy(quote_order_qty=trade_size_usdt)

        # 2. Se a compra falhar, não registrar o trade no DB
        if not buy_successful:
            self.logger.error("A ordem de compra falhou. O trade não será registrado no banco de dados.")
            return

        # 3. Se a compra for bem-sucedida, registrar o trade
        try:
            entry_price = candle['close']
            atr = candle['atr_14']
            if pd.isna(atr) or atr == 0:
                self.logger.warning("ATR inválido, não é possível calcular SL/TP. Posição não será aberta.")
                return

            profit_target_price = entry_price + (atr * self.profit_target_mult)
            stop_loss_price = entry_price - (atr * self.stop_loss_mult)
            # A quantidade real de BTC virá da resposta da exchange no futuro, por enquanto calculamos
            quantity_btc = trade_size_usdt / entry_price

            trade_data = {
                "trade_id": str(uuid.uuid4()),
                "status": "OPEN",
                "entry_price": entry_price,
                "quantity_btc": quantity_btc,
                "profit_target_price": profit_target_price,
                "stop_loss_price": stop_loss_price,
                "timestamp": datetime.now(timezone.utc),
                "decision_data": decision_data or {},
                "total_realized_pnl_usdt": 0.0,
            }
            self.db_manager.write_trade(trade_data)
            self.logger.info(f"Trade {trade_data['trade_id']} aberto e registrado com sucesso.")

        except Exception as e:
            self.logger.critical(f"CRÍTICO: A ORDEM DE COMPRA FOI EXECUTADA, MAS FALHOU AO REGISTRAR NO DB! Verifique manualmente. Erro: {e}", exc_info=True)

    def check_and_close_positions(self, candle: pd.Series):
        closed_trades_summaries = []
        current_price = candle['close']
        open_positions_df = self.db_manager.get_open_positions()
        commission_rate = self.config.backtest.commission_rate
        trailing_config = self.config.trailing_profit

        if open_positions_df.empty:
            return []

        trades_to_partially_close = []

        for trade_id, position in open_positions_df.iterrows():
            # --- LÓGICA DE TRAILING PROFIT TARGET ---
            unrealized_pnl_percent = (current_price - position['entry_price']) / position['entry_price']
            if unrealized_pnl_percent >= (trailing_config.activation_percentage / 100.0):
                new_profit_target = current_price * (1 - (trailing_config.trailing_percentage / 100.0))
                if new_profit_target > position['profit_target_price']:
                    self.logger.info(f"🚀 ATUALIZANDO PROFIT TARGET PARA O TRADE {trade_id}:")
                    self.logger.info(f"   Antigo Alvo: ${position['profit_target_price']:,.2f}")
                    self.logger.info(f"   Novo Alvo:   ${new_profit_target:,.2f}")
                    self.db_manager.write_trade({
                        "trade_id": trade_id,
                        "status": "OPEN",
                        "profit_target_price": new_profit_target,
                        "timestamp": datetime.now(timezone.utc)
                    })
                    position['profit_target_price'] = new_profit_target

            # Check if trade is eligible for partial take profit
            decision_data = position.get('decision_data', {})
            is_partially_closed = decision_data.get('partially_closed', False)

            if not is_partially_closed and current_price >= position['profit_target_price']:
                entry_cost = position['entry_price'] * position['quantity_btc']
                exit_value = current_price * position['quantity_btc']
                commission = (entry_cost + exit_value) * commission_rate
                net_pnl = exit_value - entry_cost - commission

                if net_pnl > self.config.trading_strategy.minimum_profit_for_take_profit:
                    trades_to_partially_close.append(position)
                else:
                    self.logger.debug(f"TAKE PROFIT for trade {trade_id} ignored due to insufficient net profit.")

        if not trades_to_partially_close:
            return []

        self.logger.info(f"Identified {len(trades_to_partially_close)} trades for partial take-profit.")

        for position in trades_to_partially_close:
            trade_id = position.name
            original_quantity = position['quantity_btc']
            quantity_to_sell = original_quantity * self.partial_sell_percent
            quantity_remaining = original_quantity - quantity_to_sell

            if quantity_remaining < 1e-8:
                quantity_remaining = 0

            entry_price = position['entry_price']
            entry_cost_sold = entry_price * quantity_to_sell
            exit_value_sold = current_price * quantity_to_sell
            commission_entry_sold = entry_cost_sold * commission_rate
            commission_exit_sold = exit_value_sold * commission_rate
            net_pnl_sold = exit_value_sold - entry_cost_sold - commission_entry_sold - commission_exit_sold

            self.logger.info(f"✅ PARTIALLY CLOSING TRADE {trade_id} (TAKE_PROFIT):")
            self.logger.info(f"   Selling {quantity_to_sell:.8f} BTC ({self.partial_sell_percent:.0%}) at ${current_price:,.2f}")
            self.logger.info(f"   Realized PnL: ${net_pnl_sold:,.2f}. Remaining: {quantity_remaining:.8f} BTC")

            sell_successful = self.account_manager.update_on_sell(quantity_btc=quantity_to_sell)

            if not sell_successful:
                self.logger.error(f"A ordem de venda para o trade {trade_id} falhou. O trade não será atualizado no DB.")
                continue

            decision_data = position.get('decision_data', {})
            decision_data['partially_closed'] = True
            decision_data['last_partial_close_ts'] = datetime.now(timezone.utc).isoformat()

            total_realized_pnl = position.get('total_realized_pnl_usdt', 0.0) + net_pnl_sold

            status = "OPEN"
            if quantity_remaining == 0:
                status = "CLOSED"

            update_trade_data = {
                "trade_id": trade_id,
                "status": status,
                "entry_price": entry_price,
                "quantity_btc": quantity_remaining,
                "total_realized_pnl_usdt": total_realized_pnl,
                "timestamp": datetime.now(timezone.utc),
                "decision_data": decision_data
            }
            self.db_manager.write_trade(update_trade_data)

            summary = {
                'entry_price': entry_price,
                'exit_price': current_price,
                'quantity_btc': quantity_to_sell,
                'pnl_usdt': net_pnl_sold,
                'exit_reason': 'TAKE_PROFIT_PARTIAL'
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

        # Lógica de decisão de entrada
        entry_decision = None
        if self.previous_candle is not None:
            if candle['close'] > self.previous_candle['close']:
                self.consecutive_green_candles += 1
            else:
                self.consecutive_green_candles = 0

        if open_trades_count == 0:
            if self.previous_candle is not None and candle['close'] < self.previous_candle['close']:
                self.logger.info("ESTRATÉGIA 'ENTRAR NO JOGO': Primeira vela de baixa detectada.")
                entry_decision = {"reason": "FIRST_ENTRY_DIP"}
            elif self.consecutive_green_candles >= self.consecutive_green_candles_for_entry:
                self.logger.info(f"ESTRATÉGIA 'ENTRAR NO JOGO': {self.consecutive_green_candles} velas verdes consecutivas detectadas.")
                entry_decision = {"reason": "UPTREND_ENTRY"}
                self.consecutive_green_candles = 0 # Reset after entry
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