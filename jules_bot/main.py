# Ficheiro: main.py (VERSÃO FINAL REATORADA)

import sys
from jules_bot.utils.logger import logger
from jules_bot.utils.config_manager import settings
from jules_bot.bot.trading_bot import TradingBot
from jules_bot.ui.app import JulesBotApp

def main():
    """
    Ponto de entrada principal da aplicação.
    Lê o modo de execução do config.yml e inicia o componente apropriado.
    """
    mode = settings.app.execution_mode
    logger.info(f"--- INICIANDO O BOT EM MODO '{mode.upper()}' ---")

    if mode == 'backtest':
        # No modo backtest, inicia a interface de usuário textual.
        app = JulesBotApp(config=settings)
        app.run()
    elif mode in ['trade', 'test']:
        # Nos modos de operação real ou teste, inicia o bot de trading.
        try:
            bot = TradingBot(mode=mode)
            bot.run()
        except Exception as e:
            logger.critical(f"❌ Falha catastrófica ao inicializar o TradingBot: {e}", exc_info=True)
            sys.exit(1)
    else:
        logger.error(f"Modo de execução '{mode}' inválido no config.yml. Use 'trade', 'test' ou 'backtest'.")
        sys.exit(1)

if __name__ == '__main__':
    main()