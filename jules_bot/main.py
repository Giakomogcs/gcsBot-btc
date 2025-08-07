import os
import sys
from jules_bot.bot.trading_bot import TradingBot
from jules_bot.utils.logger import logger

def main():
    """
    Ponto de entrada principal do bot.
    Lê o modo de execução da variável de ambiente BOT_MODE e chama a função correta.
    """
    # Garante que qualquer espaço em branco seja removido antes de comparar
    bot_mode = os.getenv('BOT_MODE', 'trade').strip().lower()
    
    logger.info(f"--- INICIANDO O BOT EM MODO '{bot_mode.upper()}' (via variável de ambiente) ---")
    
    if bot_mode not in ['trade', 'test', 'backtest']:
        logger.error(f"Modo inválido '{bot_mode}'. Deve ser 'trade', 'test', ou 'backtest'.")
        sys.exit(1)

    bot = None
    try:
        bot = TradingBot(mode=bot_mode)
        
        # --- CORREÇÃO: Direciona para a função correta com base no modo ---
        if bot_mode == 'backtest':
            logger.info("Modo 'backtest' detectado. Chamando bot.run_backtest().")
            bot.run_backtest()
        else:
            logger.info(f"Modo '{bot_mode}' detectado. Chamando bot.run().")
            bot.run()

    except Exception as e:
        logger.critical(f"Erro fatal ao executar o bot: {e}", exc_info=True)
        sys.exit(1)
    finally:
        logger.info("--- Encerrando o bot ---")
        if bot:
            bot.shutdown()

if __name__ == "__main__":
    main()
