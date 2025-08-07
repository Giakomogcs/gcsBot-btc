# src/core/trading_bot.py (VERSÃO FINAL COM CALCULADORA DE FEATURES)

import time
import pandas as pd
import uuid
from datetime import datetime, timezone
import signal
import sys
import json
import os
from typing import Any

from jules_bot.utils.logger import logger
from jules_bot.utils.config_manager import settings
from jules_bot.bot.position_manager import PositionManager
from jules_bot.core.exchange_connector import ExchangeManager
from jules_bot.bot.account_manager import AccountManager
from jules_bot.database.database_manager import DatabaseManager
from jules_bot.database.data_manager import DataManager

class TradingBot:
    """
    O maestro que orquestra todos os componentes do bot, utilizando um
    calculador de features em tempo real para tomar decisões.
    """

    def __init__(self, mode: str):
        self.is_running = False
        self.mode = mode
        logger.info(f"--- INICIALIZANDO O TRADING BOT EM MODO '{self.mode.upper()}' ---")

        # --- ETAPA 1: Construção dos Managers ---
        logger.info("Construindo e injetando dependências...")
        # Instancia o DatabaseManager com o modo de execução correto
        self.db_manager = DatabaseManager(execution_mode=self.mode)
        self.exchange_manager = ExchangeManager(mode=self.mode)
        self.account_manager = AccountManager(binance_client=self.exchange_manager._client)
        self.position_manager = PositionManager(
            db_manager=self.db_manager,
            account_manager=self.account_manager,
            exchange_manager=self.exchange_manager
        )
        
        self.symbol = settings.app.symbol

        # --- ETAPA 3: Reconciliação de Estado ---
        self.position_manager.reconcile_states()

        # --- ETAPA 4: Finalização da Inicialização ---
        logger.info("✅ Bot inicializado com sucesso. Pressione Ctrl+C para encerrar.")



    def run(self):
        """
        O loop principal que executa a lógica de trading a cada minuto.
        """
        self.is_running = True
        logger.info(f"🚀 --- LOOP PRINCIPAL INICIADO PARA O SÍMBOLO {self.symbol} --- 🚀")
        logger.info(f"Bot is running in {self.mode.upper()} mode. Press Ctrl+C to exit gracefully.")

        while self.is_running:
            try:
                # --- ETAPA 1: OBTER O PREÇO ATUAL ---
                current_price = self.exchange_manager.get_current_price(self.symbol)

                if not current_price:
                    logger.error("Não foi possível obter o preço atual. A saltar ciclo.")
                    time.sleep(10)
                    continue
                
                logger.info(f"Preço atual de {self.symbol}: ${current_price:,.2f}")

                # --- ETAPA 2: PROCESSAR COMANDOS MANUAIS ---
                self.position_manager.process_manual_commands()

                # --- ETAPA 3: EXECUTAR A LÓGICA DE TRADING AUTOMATIZADA ---
                self.position_manager.manage_positions(current_price)
                
                # --- ETAPA 4: LOGAR O ESTADO ATUAL ---
                self.log_current_state()

                logger.info("--- Ciclo concluído. A aguardar 10 segundos... ---")
                time.sleep(10)

            except KeyboardInterrupt:
                logger.info("\n[SHUTDOWN] Ctrl+C detectado. A parar o loop principal...")
                self.is_running = False

            except Exception as e:
                logger.critical(f"❌ Ocorreu um erro crítico no loop principal: {e}", exc_info=True)
                logger.info("A aguardar 5 minutos antes de reiniciar o loop para evitar spam de erros.")
                time.sleep(300)

    def shutdown(self):
        """Handles all cleanup operations to ensure a clean exit."""
        print("[SHUTDOWN] Starting graceful shutdown procedure...")

        # Example cleanup tasks:
        if hasattr(self, 'db_manager') and self.db_manager:
            self.db_manager.close_client()
            print("[SHUTDOWN] InfluxDB client closed.")

        if hasattr(self, 'exchange_manager') and self.exchange_manager:
            self.exchange_manager.close_connection()
            print("[SHUTDOWN] Exchange connection closed.")

        print("[SHUTDOWN] Cleanup complete. Goodbye!")

    def log_current_state(self):
        """Dumps the current state of the bot to a JSON file for the UI to read."""
        open_positions = self.db_manager.get_open_positions()
        # Convert DataFrame to list of dicts for JSON serialization
        positions_list = open_positions.to_dict(orient='records') if not open_positions.empty else []

        state = {
            "timestamp": time.time(),
            "is_running": self.is_running,
            "mode": self.mode,
            "open_positions": positions_list,
            "recent_high_price": self.position_manager.recent_high_price
        }
        # Note: This path needs to be accessible from where the daemon is running.
        # Since we do os.chdir("/"), we should use an absolute path.
        with open("/tmp/bot_state.json", "w") as f:
            json.dump(state, f, indent=4)
