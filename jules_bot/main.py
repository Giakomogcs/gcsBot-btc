import os
import sys
import uuid
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

        # --- Sincronização de Histórico ---
        # Antes de iniciar o bot, garante que o banco de dados local está
        # sincronizado com o histórico de trades da exchange.
        try:
            from jules_bot.core.exchange_connector import ExchangeManager
            from jules_bot.bot.synchronization_manager import SynchronizationManager
            from binance.exceptions import BinanceAPIException

            logger.info("Iniciando a sincronização do histórico de trades com a Binance...")
            
            exchange_manager = ExchangeManager(mode=bot_mode)
            symbol = config_manager.get('APP', 'symbol')

            from jules_bot.core_logic.strategy_rules import StrategyRules
            strategy_rules = StrategyRules(config_manager)
            sync_manager = SynchronizationManager(
                binance_client=exchange_manager.client,
                db_manager=db_manager,
                symbol=symbol,
                environment=bot_mode,
                strategy_rules=strategy_rules
            )
            sync_manager.run_full_sync()
            logger.info("Sincronização do histórico de trades concluída com sucesso.")

        except ValueError as e:
            # Erro comum se as chaves de API não estiverem no .env
            logger.error(f"Erro de configuração: {e}", exc_info=True)
            bot_prefix = bot_name.upper()
            if 'test' in str(e).lower():
                logger.critical(f"DICA: Verifique se as variáveis '{bot_prefix}_BINANCE_TESTNET_API_KEY' e '{bot_prefix}_BINANCE_TESTNET_API_SECRET' estão definidas corretamente no seu arquivo .env")
            else:
                logger.critical(f"DICA: Verifique se as variáveis '{bot_prefix}_BINANCE_API_KEY' e '{bot_prefix}_BINANCE_API_SECRET' estão definidas corretamente no seu arquivo .env")
            raise RuntimeError("Falha na configuração das chaves de API, abortando.")
        
        except BinanceAPIException as e:
            # Erro se as chaves estiverem presentes mas forem inválidas/expiradas/etc.
            logger.error(f"Erro de API da Binance: {e}", exc_info=True)
            logger.critical("A conexão com a Binance falhou. Isso geralmente ocorre por chaves de API inválidas, expiradas ou sem as permissões corretas ('Enable Reading' e 'Enable Spot & Margin Trading').")
            raise RuntimeError("Falha na conexão com a API da Binance, abortando.")

        except Exception as e:
            logger.error(f"Ocorreu um erro inesperado durante a sincronização do histórico: {e}", exc_info=True)
            raise RuntimeError("Falha na sincronização do histórico, abortando a inicialização do bot.")

        # --- Instanciação do Bot ---
        # O nome do bot é para configuração. O run_id é para identificar esta sessão específica.
        run_id = str(uuid.uuid4())
        logger.info(f"Bot Name: {bot_name}, Unique Run ID: {run_id}")

        # O TradingBot recebe o MarketDataProvider.
        # Internamente, o TradingBot e seus componentes (como StateManager)
        # criarão suas próprias instâncias do PostgresManager conforme necessário.
        bot = TradingBot(
            mode=bot_mode,
            bot_id=run_id, # Passando o ID único para a sessão
            market_data_provider=market_data_provider,
            db_manager=db_manager
        )
        
        logger.info(f"Bot instanciado com sucesso em modo '{bot_mode}'.")
        bot.run()

    except Exception as e:
        logger.critical(f"Erro fatal ao executar o bot: {e}", exc_info=True)
        # Manter o container vivo por um tempo para permitir a inspeção de logs em ambientes Docker.
        import time
        logger.info("Ocorreu um erro fatal. O bot irá encerrar em 5 minutos. Use 'docker logs' para inspecionar o erro.")
        time.sleep(300)
        sys.exit(1)
    finally:
        logger.info("--- Encerrando o bot ---")
        if bot:
            bot.shutdown()

if __name__ == "__main__":
    main()