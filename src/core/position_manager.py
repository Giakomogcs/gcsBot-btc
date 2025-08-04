# Ficheiro: src/core/position_manager.py (VERSÃO ESTRATEGA GRID-DCA)

import pandas as pd
import uuid
from datetime import datetime, timezone
import json

from src.logger import logger
from src.database_manager import db_manager
from src.config_manager import settings

class PositionManager:
    def __init__(self, config):
        self.position_config = config.position_management
        self.sizing_config = config.dynamic_sizing
        self.strategy_config = config.trading_strategy.triple_barrier

        self.profit_target_mult = self.strategy_config.profit_mult
        self.stop_loss_mult = self.strategy_config.stop_mult
        
        # --- NOVOS PARÂMETROS ESTRATÉGICOS ---
        # Limiar de confiança mais baixo apenas para a PRIMEIRA entrada
        self.first_entry_confidence_factor = 0.80 # Exige 80% da confiança normal
        # Gatilho para comprar mais: se o preço cair X% abaixo da última compra
        self.buy_the_dip_trigger_percent = -2.0 / 100 # Queda de 2%

        self.performance_factor = 1.0

    # ... (_update_performance_factor e get_capital_per_trade permanecem iguais)
    def _update_performance_factor(self):
        # ... (sem alterações)
        if not self.sizing_config.enabled: self.performance_factor = 1.0; return
        n_trades = self.sizing_config.performance_window_trades
        trades_df = db_manager.get_last_n_trades(n=n_trades)
        if trades_df.empty or len(trades_df) < n_trades: self.performance_factor = 1.0; return
        gross_profit = trades_df[trades_df['pnl'] > 0]['pnl'].sum()
        gross_loss = abs(trades_df[trades_df['pnl'] < 0]['pnl'].sum())
        profit_factor = float('inf') if gross_loss == 0 else gross_profit / gross_loss
        logger.info(f"Análise de Performance: Últimos {len(trades_df)} trades. Profit Factor: {profit_factor:.2f}")
        if profit_factor > self.sizing_config.profit_factor_threshold:
            self.performance_factor = self.sizing_config.performance_upscale_factor
        else:
            self.performance_factor = self.sizing_config.performance_downscale_factor
            
    def get_capital_per_trade(self, available_capital: float) -> float:
        # ... (sem alterações)
        self._update_performance_factor()
        base_risk_percent = self.position_config.capital_per_trade_percent / 100
        dynamic_risk_percent = base_risk_percent * self.performance_factor
        trade_size_usdt = available_capital * min(dynamic_risk_percent, 0.10)
        return trade_size_usdt

    def open_position(self, candle: pd.Series, decision_data: dict = None):
        # ... (esta função permanece a mesma)
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
            db_manager.write_trade(trade_data)
        except Exception as e:
            logger.error(f"Erro ao tentar abrir posição: {e}", exc_info=True)

    def check_and_close_positions(self, candle: pd.Series):
        # ... (esta função permanece a mesma)
        closed_trades_summaries = []
        current_price = candle['close']
        open_positions_df = db_manager.get_open_positions()
        if open_positions_df.empty: return []
        for trade_id, position in open_positions_df.iterrows():
            exit_reason = None
            if current_price >= position['profit_target_price']: exit_reason = 'TAKE_PROFIT'
            elif current_price <= position['stop_loss_price']: exit_reason = 'STOP_LOSS'
            if exit_reason:
                pnl = (current_price - position['entry_price']) * position['quantity_btc']
                close_trade_data = {
                    "trade_id": trade_id, "status": "CLOSED", "entry_price": position['entry_price'],
                    "realized_pnl_usdt": pnl, "timestamp": datetime.now(timezone.utc),
                    "decision_data": {"exit_reason": exit_reason}
                }
                db_manager.write_trade(close_trade_data)
                summary = {
                    'entry_price': position['entry_price'], 'exit_price': current_price,
                    'quantity_btc': position['quantity_btc'], 'pnl_usdt': pnl,
                    'exit_reason': exit_reason
                }
                closed_trades_summaries.append(summary)
        return closed_trades_summaries

    def get_open_positions(self) -> pd.DataFrame:
        """Retorna um DataFrame com as posições abertas."""
        return db_manager.get_open_positions()

    def check_for_entry(self, candle: pd.Series, signal: str, decision_report: dict):
        """
        Nova lógica de entrada estratégica. Decide se faz a primeira compra ou se compra mais na baixa.
        """
        open_positions = self.get_open_positions()
        open_trades_count = len(open_positions)
        max_trades = self.position_config.max_concurrent_trades

        # Se já atingimos o limite de posições, não fazemos nada.
        if open_trades_count >= max_trades:
            return

        # --- ESTRATÉGIA 1: ENTRAR NO JOGO (PRIMEIRO TRADE) ---
        if open_trades_count == 0:
            required_confidence = decision_report.get('required_confidence', 1.0) * self.first_entry_confidence_factor
            if signal == "BUY" and decision_report.get('final_confidence', 0) >= required_confidence:
                logger.info(f"ESTRATÉGIA 'ENTRAR NO JOGO': Condições de primeira entrada atingidas. Confiança: {decision_report.get('final_confidence', 0):.2%}, Limiar Ajustado: {required_confidence:.2%}")
                self.execute_buy(candle, decision_report)
            return

        # --- ESTRATÉGIA 2: COMPRAR NA BAIXA (GRID-DCA) ---
        if open_trades_count > 0:
            last_trade_price = open_positions['entry_price'].iloc[-1]
            current_price = candle['close']
            price_change_percent = (current_price - last_trade_price) / last_trade_price

            if price_change_percent <= self.buy_the_dip_trigger_percent:
                logger.info(f"ESTRATÉGIA 'COMPRAR NA BAIXA': Preço caiu {price_change_percent:.2%} (abaixo do gatilho de {self.buy_the_dip_trigger_percent:.2%}). Comprando mais.")
                self.execute_buy(candle, {"reason": "BUY_THE_DIP"})
            return

    def execute_buy(self, candle: pd.Series, decision_report: dict):
        """Função auxiliar que executa a lógica de compra."""
        # Esta função seria usada no backtester e no bot ao vivo para simular/executar a compra.
        # No contexto do backtest, o capital virá do backtester.
        # No bot ao vivo, viria do exchange_manager.
        # Por agora, o importante é que a decisão de chamar esta função está correta.
        pass # A lógica de execução em si fica no backtester/main.py