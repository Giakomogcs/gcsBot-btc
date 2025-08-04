# Ficheiro: src/core/position_manager.py (VERSÃO ESTRATEGA GRID-DCA)

import pandas as pd
import uuid
from datetime import datetime, timezone
import json
from typing import Optional

class PositionManager:
    def __init__(self, config, db_manager, logger):
        self.config = config
        self.db_manager = db_manager
        self.logger = logger

        self.position_config = self.config.position_management
        self.sizing_config = self.config.dynamic_sizing
        self.strategy_config = self.config.trading_strategy

        self.profit_target_mult = self.strategy_config.triple_barrier.profit_mult
        self.stop_loss_mult = self.strategy_config.triple_barrier.stop_mult
        
        # --- NOVOS PARÂMETROS ESTRATÉGICOS ---
        self.first_entry_confidence_factor = self.strategy_config.first_entry_confidence_factor
        self.dca_grid_spacing_percent = self.strategy_config.dca_grid_spacing_percent / 100.0

        self.performance_factor = 1.0

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

        if open_positions_df.empty:
            return []

        for trade_id, position in open_positions_df.iterrows():
            exit_reason = None
            if current_price >= position['profit_target_price']:
                exit_reason = 'TAKE_PROFIT'
            elif current_price <= position['stop_loss_price']:
                exit_reason = 'STOP_LOSS'

            if exit_reason:
                pnl = (current_price - position['entry_price']) * position['quantity_btc']
                close_trade_data = {
                    "trade_id": trade_id, "status": "CLOSED", "entry_price": position['entry_price'],
                    "realized_pnl_usdt": pnl, "timestamp": datetime.now(timezone.utc),
                    "decision_data": {"exit_reason": exit_reason}
                }
                self.db_manager.write_trade(close_trade_data)
                summary = {
                    'entry_price': position['entry_price'], 'exit_price': current_price,
                    'quantity_btc': position['quantity_btc'], 'pnl_usdt': pnl,
                    'exit_reason': exit_reason
                }
                closed_trades_summaries.append(summary)
        return closed_trades_summaries

    def get_open_positions(self) -> pd.DataFrame:
        """Retorna um DataFrame com as posições abertas."""
        return self.db_manager.get_open_positions()

    def check_for_entry(self, candle: pd.Series, decision_report: dict) -> Optional[dict]:
        """
        Nova lógica de entrada estratégica. Decide se faz a primeira compra ou se compra mais na baixa.
        Retorna o decision_report se uma compra deve ser executada, caso contrário None.
        """
        open_positions = self.get_open_positions()
        open_trades_count = len(open_positions)
        max_trades = self.position_config.max_concurrent_trades

        if open_trades_count >= max_trades:
            return None

        signal = decision_report.get('signal', 'NEUTRAL')
        final_confidence = decision_report.get('final_confidence', 0)
        static_threshold = self.strategy_config.static_confidence_threshold

        # --- ESTRATÉGIA 1: ENTRAR NO JOGO (PRIMEIRO TRADE) ---
        if open_trades_count == 0:
            required_confidence = static_threshold * self.first_entry_confidence_factor
            if signal == "BUY" and final_confidence >= required_confidence:
                self.logger.info(f"ESTRATÉGIA 'ENTRAR NO JOGO': Condições de primeira entrada atingidas. Confiança: {final_confidence:.2%}, Limiar Ajustado: {required_confidence:.2%}")
                return decision_report
            return None

        # --- ESTRATÉGIA 2: COMPRAR NA BAIXA (GRID-DCA) ---
        if open_trades_count > 0:
            average_entry_price = open_positions['entry_price'].mean()
            current_price = candle['close']
            price_change_percent = (current_price - average_entry_price) / average_entry_price

            if price_change_percent <= self.dca_grid_spacing_percent:
                self.logger.info(f"ESTRATÉGIA 'COMPRAR NA BAIXA': Preço caiu {price_change_percent:.2%} abaixo da média ({average_entry_price:.2f}). Gatilho: {self.dca_grid_spacing_percent:.2%}. Comprando mais.")
                return {"reason": "DCA_GRID_ENTRY"}
            return None

        return None