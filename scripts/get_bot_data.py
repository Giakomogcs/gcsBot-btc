import asyncio
import json
import os
import sys
import typer
# Add project root to sys.path to allow imports from other directories
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from jules_bot.utils.config_manager import config_manager
from jules_bot.database.postgres_manager import PostgresManager
from jules_bot.services.status_service import StatusService
from jules_bot.research.live_feature_calculator import LiveFeatureCalculator
from jules_bot.utils.logger import logger

def _check_environment(mode: str, db_manager: PostgresManager):
    """Verifica se as dependências do ambiente (chaves de API, DB) estão configuradas."""
    # 1. Verificar chaves de API da Binance
    if mode == 'test':
        api_key = os.getenv('BINANCE_TESTNET_API_KEY')
        api_secret = os.getenv('BINANCE_TESTNET_API_SECRET')
        if not api_key or not api_secret:
            logger.error("ERRO DE CONFIGURAÇÃO: As chaves da API de Testnet da Binance não foram encontradas.")
            logger.error("Por favor, copie '.env.example' para '.env' e verifique se as variáveis BINANCE_TESTNET_API_KEY e BINANCE_TESTNET_API_SECRET estão definidas.")
            logger.error("Lembre-se de que este script deve ser executado através do 'run.py' para carregar o ambiente corretamente.")
            raise typer.Exit(code=1)
    elif mode == 'trade':
        api_key = os.getenv('BINANCE_API_KEY')
        api_secret = os.getenv('BINANCE_API_SECRET')
        if not api_key or not api_secret:
            logger.error("ERRO DE CONFIGURAÇÃO: As chaves da API de Produção da Binance não foram encontradas.")
            logger.error("Por favor, verifique se as variáveis BINANCE_API_KEY e BINANCE_API_SECRET estão definidas no seu arquivo .env.")
            raise typer.Exit(code=1)

    # 2. Verificar conexão com o banco de dados
    is_connected, error_msg = db_manager.check_connection()
    if not is_connected:
        db_config = db_manager.engine.url
        logger.error("ERRO DE CONEXÃO COM O BANCO DE DADOS: Não foi possível conectar ao PostgreSQL.")
        logger.error(f"   Host: {db_config.host}:{db_config.port}")
        logger.error(f"   Database: {db_config.database}")
        logger.error(f"   Usuário: {db_config.username}")
        logger.error(f"   Erro original: {error_msg}")
        logger.error("\n   Possíveis Soluções:")
        logger.error("   1. Verifique se os serviços Docker estão em execução com 'python run.py status'.")
        logger.error("   2. Se não estiverem, inicie-os com 'python run.py start'.")
        logger.error("   3. Certifique-se de que você está executando este comando através do 'run.py' (ex: 'python run.py dashboard').")
        raise typer.Exit(code=1)

def main(
    mode: str = typer.Argument(
        "test",
        help="The environment to get data for ('trade' or 'test')."
    )
):
    """
    Fetches and displays a comprehensive status report for the trading bot.

    This script provides a snapshot of the bot's state, including:
    - Current BTC price
    - Detailed status of all open positions (including PnL and sell target progress)
    - Status of the buy signal strategy
    - Full trade history for the environment
    - Live wallet balances from the exchange
    """
    if mode not in ["trade", "test"]:
        logger.error("Invalid mode specified. Please choose 'trade' or 'test'.")
        raise typer.Exit(code=1)

    bot_name = os.getenv("BOT_NAME")
    if not bot_name:
        logger.error("ERRO CRÍTICO: A variável de ambiente BOT_NAME não está definida.")
        # Print JSON error to stderr for TUI to catch
        print(json.dumps({"error": "BOT_NAME environment variable not set."}), file=sys.stderr)
        raise typer.Exit(code=1)

    logger.info(f"Gathering bot data for '{bot_name}' in '{mode}' environment...")

    try:
        # 1. Initialize ConfigManager
        config_manager.initialize(bot_name)

        # 2. Instantiate services
        db_manager = PostgresManager()

        # 3. Check environment dependencies (API keys, DB connection)
        _check_environment(mode, db_manager)

        # 4. Proceed with main logic
        logger.info("Ambiente verificado. Coletando dados do bot...")
        feature_calculator = LiveFeatureCalculator(db_manager, mode=mode)
        status_service = StatusService(db_manager, config_manager, feature_calculator)
        
        status_data = status_service.get_extended_status(mode, bot_name)

        if "error" in status_data:
            logger.error(f"O serviço de status retornou um erro: {status_data['error']}")
            raise typer.Exit(code=1)

        print(json.dumps(status_data, indent=4, default=str))
        logger.info("Dados do bot recuperados com sucesso.")

    except Exception as e:
        logger.error(f"Ocorreu um erro crítico ao buscar o status do bot: {e}", exc_info=True)
        raise typer.Exit(code=1)

if __name__ == "__main__":
    typer.run(main)