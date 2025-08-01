# Ficheiro: src/core/position_manager.py (VERSÃO CORRIGIDA)

import pandas as pd
import uuid
from datetime import datetime, timezone

from src.logger import logger
from src.database_manager import db_manager
from src.config_manager import settings

from src.core.exchange_manager import exchange_manager


class PositionManager:
    def __init__(self, config):
        self.position_config = config.position_management
        self.sizing_config = config.dynamic_sizing

        self.profit_target_percent = self.position_config.profit_target_percent / 100
        self.performance_factor = 1.0

    def _update_performance_factor(self):
        """
        Calcula o Profit Factor dos últimos N trades e ajusta o fator de performance.
        """
        if not self.sizing_config.enabled:
            self.performance_factor = 1.0
            return

        n_trades = self.sizing_config.performance_window_trades
        trades_df = db_manager.get_last_n_trades(n=n_trades)

        if trades_df.empty or len(trades_df) < n_trades:
            self.performance_factor = 1.0
            return

        gross_profit = trades_df[trades_df['pnl'] > 0]['pnl'].sum()
        gross_loss = abs(trades_df[trades_df['pnl'] < 0]['pnl'].sum())

        if gross_loss == 0:
            profit_factor = float('inf')
        else:
            profit_factor = gross_profit / gross_loss

        logger.info(f"Análise de Performance: Últimos {len(trades_df)} trades. Profit Factor: {profit_factor:.2f}")

        if profit_factor > self.sizing_config.profit_factor_threshold:
            self.performance_factor = self.sizing_config.performance_upscale_factor
            logger.info(f"Performance ALTA. Ajustando fator para: {self.performance_factor}")
        else:
            self.performance_factor = self.sizing_config.performance_downscale_factor
            logger.info(f"Performance BAIXA. Ajustando fator para: {self.performance_factor}")

    def get_capital_per_trade(self, available_capital: float) -> float:
        """
        Calcula o montante de capital a ser usado no próximo trade, ajustado pelo fator de performance.
        """
        self._update_performance_factor()

        base_risk_percent = self.position_config.capital_per_trade_percent / 100
        dynamic_risk_percent = base_risk_percent * self.performance_factor
        final_risk_percent = min(dynamic_risk_percent, 0.10)
        trade_size_usdt = available_capital * final_risk_percent
        logger.info(f"Cálculo de capital: {available_capital:,.2f} * ({base_risk_percent:.2%} * {self.performance_factor}) = ${trade_size_usdt:,.2f}")
        return trade_size_usdt

    def open_position(self, entry_price: float, quantity_btc: float):
        """Abre uma nova posição e a regista na base de dados."""
        try:
            profit_target_price = entry_price * (1 + self.profit_target_percent)
            trade_data = {
                "trade_id": str(uuid.uuid4()),
                "status": "OPEN",
                "entry_price": entry_price,
                "profit_target_price": profit_target_price,
                "quantity_btc": quantity_btc,
                "timestamp": datetime.now(timezone.utc)
            }
            db_manager.write_trade(trade_data)
        except Exception as e:
            logger.error(f"Erro ao tentar abrir posição: {e}", exc_info=True)

    def check_and_close_positions(self, current_candle: pd.Series):
        """Verifica as posições abertas para ver se alguma deve ser fechada."""
        closed_trades_summaries = []
        current_price = current_candle['close']
        open_positions_df = db_manager.get_open_positions()
        if open_positions_df.empty:
            return []
        for trade_id, position in open_positions_df.iterrows():
            if current_price >= position['profit_target_price']:
                pnl = (current_price - position['entry_price']) * position['quantity_btc']
                close_trade_data = {
                    "trade_id": trade_id, "status": "CLOSED",
                    "entry_price": position['entry_price'], "realized_pnl_usdt": pnl,
                    "timestamp": datetime.now(timezone.utc)
                }
                db_manager.write_trade(close_trade_data)
                summary = {
                    'entry_price': position['entry_price'], 'exit_price': current_price,
                    'quantity_btc': position['quantity_btc'], 'pnl_usdt': pnl,
                    'exit_reason': 'TAKE_PROFIT'
                }
                closed_trades_summaries.append(summary)
        return closed_trades_summaries

    def get_open_positions_count(self) -> int:
        """Retorna o número de posições abertas diretamente do banco de dados."""
        return len(db_manager.get_open_positions())

    def check_for_entry(self, signal: str, current_price: float):
        """
        Verifica um sinal de entrada e decide se abre uma nova posição.
        Orquestra a lógica de verificação de limites, capital e execução.
        """
        if signal != "BUY":
            return

        try:
            max_trades = self.position_config.max_concurrent_trades
            open_trades_count = self.get_open_positions_count()
            if open_trades_count >= max_trades:
                logger.info(f"Limite de posições ({max_trades}) atingido. Nenhuma nova entrada será feita.")
                return

            logger.info(f"Sinal de 'BUY' recebido. Verificando condições para entrada. Posições abertas: {open_trades_count}/{max_trades}")

            available_capital = exchange_manager.get_account_balance(asset='USDT')
            if not available_capital or available_capital < 10:
                logger.warning(f"Saldo insuficiente em USDT ({available_capital}) para abrir nova posição.")
                return

            trade_size_usdt = self.get_capital_per_trade(available_capital)
            symbol = settings.app.symbol

            order_response = exchange_manager.place_market_order(
                symbol=symbol,
                side='BUY',
                quantity=trade_size_usdt
            )

            if order_response and order_response.get('status') == 'FILLED':
                quantity_btc = float(order_response.get('executedQty', 0.0))
                if quantity_btc > 0:
                    self.open_position(entry_price=current_price, quantity_btc=quantity_btc)
                else:
                    logger.error("Ordem de compra supostamente preenchida, mas a quantidade de BTC é zero.")
            else:
                logger.error("Falha ao executar a ordem de compra ou a ordem não foi preenchida.")

        except Exception as e:
            logger.error(f"Erro no processo de verificação de entrada: {e}", exc_info=True)