# src/core/trading_bot.py (VERSÃO FINAL COM CALCULADORA DE FEATURES)

import time
import pandas as pd
from datetime import datetime, timezone
import signal
import sys
import json
import os
from typing import Any

from gcs_bot.utils.logger import logger
from gcs_bot.utils.config_manager import settings
from gcs_bot.core.position_manager import PositionManager
from gcs_bot.core.exchange_manager import ExchangeManager
from gcs_bot.core.account_manager import AccountManager
from gcs_bot.database.database_manager import db_manager
from gcs_bot.data.data_manager import DataManager
# --- NOVA IMPORTAÇÃO ESSENCIAL ---
from gcs_bot.core.live_feature_calculator import LiveFeatureCalculator

class TradingBot:
    """
    O maestro que orquestra todos os componentes do bot, utilizando um
    calculador de features em tempo real para tomar decisões.
    """

    def __init__(self, mode: str = 'trade'):
        self.mode = mode
        logger.info(f"--- INICIALIZANDO O TRADING BOT EM MODO '{self.mode.upper()}' ---")

        # --- ETAPA 1: Construção dos Managers ---
        logger.info("Construindo e injetando dependências...")
        exchange_manager = ExchangeManager(mode=self.mode)
        self.account_manager = AccountManager(binance_client=exchange_manager._client)
        data_manager = DataManager(db_manager=db_manager, config=settings, logger=logger)
        self.feature_calculator = LiveFeatureCalculator(data_manager, mode=self.mode)
        self.position_manager = PositionManager(
            config=settings,
            db_manager=db_manager,
            logger=logger,
            account_manager=self.account_manager
        )
        
        self.symbol = settings.app.symbol

        # --- ETAPA 2: SINCRONIZAÇÃO DE POSIÇÕES (NOVO BLOCO) ---
        # Este bloco garante que o bot "conheça" os trades feitos anteriormente.
        if self.mode in ['test', 'trade']:
            logger.info("Iniciando processo de sincronização de trades órfãos...")
            try:
                # a) Busque os trades recentes da corretora (ex: últimos 100)
                recent_trades_df = self.account_manager.get_trade_history(limit=100)

                if recent_trades_df is not None and not recent_trades_df.empty:
                    # b) Busque dados históricos com features (ATR) para calcular os alvos
                    historical_data_df = data_manager.read_data_from_influx(
                        measurement="features_master_table", 
                        start_date="-3d" # Garante cobertura para trades dos últimos dias
                    )

                    if not historical_data_df.empty:
                        # c) Execute a sincronização
                        self.position_manager.synchronize_with_exchange(
                            recent_exchange_trades=pd.DataFrame(recent_trades_df),
                            historical_data=historical_data_df
                        )
                    else:
                        logger.warning("Não foi possível carregar dados históricos para o cálculo do ATR. Sincronização pulada.")
                else:
                    logger.info("Nenhum trade encontrado na corretora para sincronizar.")
            except Exception as e:
                logger.error(f"Falha durante a sincronização de trades: {e}", exc_info=True)


        # --- ETAPA 3: Finalização da Inicialização ---
        self.is_running = True
        signal.signal(signal.SIGINT, self.graceful_shutdown)
        signal.signal(signal.SIGTERM, self.graceful_shutdown)
        logger.info("✅ Bot inicializado com sucesso. Pressione Ctrl+C para encerrar.")



    def run(self):
        """
        O loop principal que executa a lógica de trading a cada minuto.
        """
        logger.info(f"🚀 --- LOOP PRINCIPAL INICIADO PARA O SÍMBOLO {self.symbol} --- 🚀")
        while self.is_running:
            try:
                # --- ETAPA 1: OBTER A VELA ATUAL COM TODAS AS FEATURES CALCULADAS ---
                current_candle = self.feature_calculator.get_current_candle_with_features()

                if current_candle.empty:
                    logger.error("Não foi possível gerar a vela de decisão. A saltar ciclo.")
                    time.sleep(60)
                    continue
                
                logger.info(f"Preço atual de {self.symbol}: ${current_candle['close']:,.2f} | ATR(14): {current_candle.get('atr_14', 0.0):.2f}")

                # --- ETAPA 2: EXECUTAR A LÓGICA DE TRADING ---
                
                # Verificar saídas (TP/SL)
                closed_trades = self.position_manager.check_and_close_positions(current_candle)
                if closed_trades:
                    for trade in closed_trades:
                        logger.info(f"✅ POSIÇÃO FECHADA ({trade['exit_reason']}): P&L de ${trade['pnl_usdt']:.2f} realizado.")

                # Verificar entradas
                buy_decision = self.position_manager.check_for_entry(current_candle)

                # Executar a compra
                if buy_decision:
                    logger.info(f"DECISÃO DE COMPRA: Motivo='{buy_decision.get('reason', 'N/A')}'. Tentando abrir posição...")
                    self.position_manager.open_position(current_candle, buy_decision)
                else:
                    logger.info("Nenhuma condição de entrada satisfeita. A aguardar.")
                
                self._update_status_file(current_candle)

                logger.info("--- Ciclo concluído. A aguardar 60 segundos... ---")
                time.sleep(60)

            except Exception as e:
                logger.critical(f"❌ Ocorreu um erro crítico no loop principal: {e}", exc_info=True)
                logger.info("A aguardar 5 minutos antes de reiniciar o loop para evitar spam de erros.")
                time.sleep(300)

    def _update_status_file(self, current_candle: pd.Series):
        """Coleta dados de status e os escreve em um arquivo JSON."""
        try:
            # 1. Dados do Portfólio
            btc_balance = self.account_manager.get_base_asset_balance()
            usd_balance = self.account_manager.get_quote_asset_balance()
            current_price = current_candle['close']
            btc_value_usdt = btc_balance * current_price
            total_value_usdt = usd_balance + btc_value_usdt

            portfolio_data = {
                "btc_balance": btc_balance,
                "usd_balance": usd_balance,
                "btc_value_usdt": btc_value_usdt,
                "total_value_usdt": total_value_usdt,
                "current_price": current_price
            }

            # 2. Estatísticas da Sessão e Posições Abertas
            all_trades = db_manager.get_all_trades_in_range(start_date="-1y")
            total_pnl = 0
            closed_trades_count = 0
            open_positions_count = 0
            open_positions_summary = []

            if not all_trades.empty:
                closed_trades = all_trades[all_trades['status'] == 'CLOSED']
                if not closed_trades.empty:
                    total_pnl = closed_trades['realized_pnl_usdt'].sum()
                closed_trades_count = len(closed_trades)

                open_positions = all_trades[all_trades['status'] == 'OPEN']
                open_positions_count = len(open_positions)

                # --- NOVA LÓGICA PARA DETALHAR POSIÇÕES ABERTAS ---
                for _, trade in open_positions.iterrows():
                    tp_price = trade.get('take_profit_price', 0)
                    distance_pct = ((tp_price - current_price) / current_price) * 100 if tp_price > 0 and current_price > 0 else 0
                    
                    open_positions_summary.append({
                        "trade_id": str(trade.name),
                        "entry_price": trade['entry_price'],
                        "quantity_btc": trade['quantity_btc'],
                        "take_profit_price": tp_price,
                        "target_distance_pct": distance_pct,
                        "timestamp": trade['timestamp'].isoformat()
                    })

            session_stats = {
                "total_pnl_usdt": total_pnl,
                "open_positions_count": open_positions_count,
                "closed_trades_count": closed_trades_count
            }

            # 3. Resumo dos Últimos 5 Trades (mantido para contexto geral)
            trade_summary = []
            if not all_trades.empty:
                last_5_trades = all_trades.sort_values(by='timestamp', ascending=False).head(5)
                for _, trade in last_5_trades.iterrows():
                    trade_summary.append({
                        "trade_id": str(trade.name), "status": trade['status'], "entry_price": trade['entry_price'],
                        "quantity_btc": trade['quantity_btc'], "timestamp": trade['timestamp'].isoformat()
                    })

            # 4. Status e Dados da Binance
            bot_status = {"last_update": datetime.now(timezone.utc).isoformat(), "symbol": self.symbol}
            open_orders_list = self.account_manager.get_open_orders()
            trade_history_list = self.account_manager.get_trade_history(limit=10)

            # 5. Montagem Final do Payload
            status_payload = {
                "portfolio": portfolio_data,
                "session_stats": session_stats,
                "bot_status": bot_status,
                "open_positions_summary": open_positions_summary,  # <-- ADICIONADO
                "trade_summary": trade_summary,
                "open_orders": open_orders_list,
                "trade_history": trade_history_list
            }

            # Escrever no arquivo
            status_file_path = os.path.join("logs", "trading_status.json")
            with open(status_file_path, 'w') as f:
                json.dump(status_payload, f, indent=4)

        except Exception as e:
            logger.error(f"Falha ao atualizar o arquivo de status: {e}", exc_info=True)


    def graceful_shutdown(self, signum: int, frame: Any) -> None:
        """Encerra o bot de forma segura."""
        logger.warning("🚨 SINAL DE INTERRUPÇÃO RECEBIDO. ENCERRANDO... 🚨")
        self.is_running = False
        sys.exit(0)