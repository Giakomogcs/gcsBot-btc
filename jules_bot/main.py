import os
import sys
from jules_bot.bot.trading_bot import TradingBot
from jules_bot.utils.logger import logger
from jules_bot.database.postgres_manager import PostgresManager
from jules_bot.core.market_data_provider import MarketDataProvider
from jules_bot.utils.config_manager import config_manager

def main():
    """
    Ponto de entrada principal do bot.
    Lê o modo de execução da variável de ambiente BOT_MODE e chama a função correta.
    """
    # O modo do bot é obrigatório e deve ser definido via variável de ambiente.
    bot_mode = os.getenv('BOT_MODE')
    if not bot_mode:
        logger.error("A variável de ambiente BOT_MODE não está definida. Defina-a como 'trade' ou 'test' para executar o bot.")
        sys.exit(1)
    
    # Garante que qualquer espaço em branco seja removido antes de comparar
    bot_mode = bot_mode.strip().lower()
    
    # Get bot name from environment variable
    bot_name = os.getenv("BOT_NAME", "jules_bot")

    # Initialize the config manager with the bot name to load correct .env variables
    config_manager.initialize(bot_name)

    logger.info(f"--- INICIANDO O BOT '{bot_name}' EM MODO '{bot_mode.upper()}' (via variável de ambiente) ---")
    
    if bot_mode not in ['trade', 'test']:
        logger.error(f"Modo inválido '{bot_mode}'. Deve ser 'trade', 'test'.")
        sys.exit(1)

    bot = None
    try:
        # --- Service Instantiation ---
        # Services that depend on the configuration (like the database) must be
        # instantiated only AFTER the config_manager has been initialized.
        db_manager = PostgresManager()
        market_data_provider = MarketDataProvider(db_manager=db_manager)

        # --- Instanciação do Bot ---
        # O nome do bot é o seu ID persistente. O run_id dentro do TradingBot será
        # usado para identificar sessões de execução específicas, se necessário.
        bot_id = bot_name
        logger.info(f"Usando ID do bot: {bot_id}")

        # O TradingBot recebe o MarketDataProvider.
        # Internamente, o TradingBot e seus componentes (como StateManager)
        # criarão suas próprias instâncias do PostgresManager conforme necessário.
        bot = TradingBot(
            mode=bot_mode,
            bot_id=bot_id, # Passando o nome do bot como ID
            market_data_provider=market_data_provider,
            db_manager=db_manager
        )
        
        logger.info(f"Bot instanciado com sucesso em modo '{bot_mode}'.")
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