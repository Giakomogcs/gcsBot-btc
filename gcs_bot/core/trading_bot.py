# src/core/trading_bot.py (VERSÃO FINAL COM CALCULADORA DE FEATURES)

import time
import pandas as pd
from datetime import datetime
import signal
import sys
from typing import Any

from gcs_bot.utils.logger import logger
from gcs_bot.utils.config_manager import settings
from gcs_bot.core.position_manager import PositionManager
from gcs_bot.core.exchange_manager import exchange_manager
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

    def __init__(self):
        logger.info("--- INICIALIZANDO O TRADING BOT EM MODO DE OPERAÇÃO ---")

        # 1. Gestores de Conexão, Conta e Dados
        self.account_manager = AccountManager(binance_client=exchange_manager._client)
        data_manager = DataManager(db_manager=db_manager, config=settings, logger=logger)

        # 2. O novo Calculador de Features em Tempo Real
        self.feature_calculator = LiveFeatureCalculator(data_manager)

        # 3. Gestor de Posição (cérebro de decisão)
        self.position_manager = PositionManager(
            config=settings,
            db_manager=db_manager,
            logger=logger,
            account_manager=self.account_manager
        )
        
        self.symbol = settings.app.symbol
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
                
                logger.info("--- Ciclo concluído. A aguardar 60 segundos... ---")
                time.sleep(60)

            except Exception as e:
                logger.critical(f"❌ Ocorreu um erro crítico no loop principal: {e}", exc_info=True)
                logger.info("A aguardar 5 minutos antes de reiniciar o loop para evitar spam de erros.")
                time.sleep(300)

    def graceful_shutdown(self, signum: int, frame: Any) -> None:
        """Encerra o bot de forma segura."""
        logger.warning("🚨 SINAL DE INTERRUPÇÃO RECEBIDO. ENCERRANDO... 🚨")
        self.is_running = False
        sys.exit(0)