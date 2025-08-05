# Ficheiro: main.py (VERSÃO FINAL REATORADA)

from gcs_bot.utils.logger import logger
from gcs_bot.core.trading_bot import TradingBot # Importa a classe principal

def main():
    """
    Ponto de entrada principal da aplicação em modo de operação.
    """
    try:
        # Cria uma instância do nosso bot.
        bot = TradingBot()
        # Inicia o loop de trading principal.
        bot.run()
    except Exception as e:
        logger.critical(f"❌ Falha catastrófica ao inicializar o TradingBot: {e}", exc_info=True)
        # Em caso de falha na inicialização, o programa termina.
        # A lógica de retry está dentro do método run() do bot.

if __name__ == '__main__':
    main()