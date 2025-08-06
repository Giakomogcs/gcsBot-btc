# Ficheiro: main.py (VERSÃO FINAL REATORADA)

import sys
from gcs_bot.utils.logger import logger
from gcs_bot.core.trading_bot import TradingBot

def main():
    """
    Ponto de entrada principal da aplicação em modo de operação.
    """
    # O modo ('trade', 'test') é passado como um argumento de linha de comando
    mode = sys.argv[1] if len(sys.argv) > 1 else 'trade'
    logger.info(f"--- INICIANDO O BOT EM MODO '{mode.upper()}' ---")

    try:
        # Cria uma instância do nosso bot, passando o modo
        bot = TradingBot(mode=mode)
        # Inicia o loop de trading principal
        bot.run()
    except Exception as e:
        logger.critical(f"❌ Falha catastrófica ao inicializar o TradingBot: {e}", exc_info=True)
        # Em caso de falha na inicialização, o programa termina.
        # A lógica de retry está dentro do método run() do bot.

if __name__ == '__main__':
    main()