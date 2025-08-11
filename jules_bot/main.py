import os
import sys
import uuid
from jules_bot.bot.trading_bot import TradingBot
from jules_bot.utils.logger import logger
from jules_bot.database.database_manager import DatabaseManager
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
    
    logger.info(f"--- INICIANDO O BOT EM MODO '{bot_mode.upper()}' (via variável de ambiente) ---")
    
    if bot_mode not in ['trade', 'test']:
        logger.error(f"Modo inválido '{bot_mode}'. Deve ser 'trade', 'test'.")
        sys.exit(1)

    bot = None
    try:
        # --- Configuração do Banco de Dados ---
        # A configuração base (URL, Token, Org) vem diretamente do ambiente
        db_connection_config = config_manager.get_db_config()

        # O provedor de dados de mercado lê do bucket de preços históricos
        prices_bucket_name = config_manager.get('INFLUXDB', 'bucket_prices')
        prices_db_config = db_connection_config.copy()
        prices_db_config['bucket'] = prices_bucket_name
        
        prices_db_manager = DatabaseManager(config=prices_db_config)
        market_data_provider = MarketDataProvider(db_manager=prices_db_manager)

        # --- Instanciação do Bot ---
        bot_id = str(uuid.uuid4())
        logger.info(f"Gerado ID único para a sessão do bot: {bot_id}")

        # O TradingBot é responsável por criar seu próprio StateManager,
        # que por sua vez obtém o bucket de negociação correto.
        bot = TradingBot(
            mode=bot_mode,
            bot_id=bot_id,
            market_data_provider=market_data_provider
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
