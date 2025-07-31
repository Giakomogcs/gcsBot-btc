# src/core/trading_bot.py (VERSÃO CORRIGIDA E LIMPA)

import pandas as pd
import signal
import sys
from typing import Any

from src.logger import logger
from src.config_manager import settings
from src.core.position_manager import PositionManager
from src.data_manager import DataManager
from src.core.account_manager import AccountManager
from src.core.portfolio_manager import PortfolioManager # Importação corrigida

class TradingBot:
    """O maestro que orquestra todos os componentes do bot."""

    def __init__(self, initial_capital_for_backtest: float = 0):
        # --- INÍCIO DA CORREÇÃO ---
        # A chamada para DataManager agora está correta (sem argumentos)
        self.data_manager = DataManager()
        self.client = self.data_manager.client
        
        # O AccountManager é para operações reais, o PortfolioManager para simulação.
        self.account_manager = AccountManager(self.client)
        
        # No backtest, usamos o capital inicial passado. Em modo real, seria o saldo da conta.
        self.portfolio = PortfolioManager(initial_capital=initial_capital_for_backtest)
        
        self.position_manager = PositionManager(settings)
        self.position_config = settings.position_management
        # --- FIM DA CORREÇÃO ---
        
        self.last_event_message = "Inicializando o bot..."
        signal.signal(signal.SIGINT, self.graceful_shutdown)
        signal.signal(signal.SIGTERM, self.graceful_shutdown)

    def graceful_shutdown(self, signum: int, frame: Any) -> None:
        """Encerra o bot de forma segura."""
        logger.warning("🚨 SINAL DE INTERRUPÇÃO RECEBIDO. ENCERRANDO... 🚨")
        sys.exit(0)