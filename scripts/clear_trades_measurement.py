import sys
import os
import argparse

# Adiciona a raiz do projeto ao path para que o jules_bot seja encontrável
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from jules_bot.utils.logger import logger
from jules_bot.utils.config_manager import config_manager
from jules_bot.database.postgres_manager import PostgresManager
from jules_bot.database.models import Trade

def main(environment: str):
    """
    Limpa todos os registros da tabela 'trades' para um ambiente específico no PostgreSQL.
    """
    try:
        # BOT_NAME is passed from the environment by the `run.py` script
        bot_name = os.getenv("BOT_NAME", "jules_bot")

        # 1. Initialize ConfigManager
        config_manager.initialize(bot_name)

        logger.info(f"--- LIMPANDO A TABELA 'TRADES' DO AMBIENTE '{environment}' PARA O BOT '{bot_name}' ---")

        # 2. Instantiate services
        db_manager = PostgresManager()

        with db_manager.get_db() as session:
            logger.info(f"Conectado ao banco de dados. Deletando trades do ambiente '{environment}'...")

            # Executa a exclusão
            num_deleted = session.query(Trade).filter(Trade.environment == environment).delete(synchronize_session=False)
            session.commit()

            logger.info(f"✅ Sucesso! {num_deleted} registros de trade foram deletados do ambiente '{environment}'.")

    except Exception as e:
        logger.error("--- ❌ ERRO CRÍTICO DURANTE A LIMPEZA DA TABELA 'TRADES' ❌ ---")
        logger.error(f"Ocorreu um erro inesperado: {e}", exc_info=True)
        # No caso de erro, a transação é revertida pelo context manager do get_db

if __name__ == "__main__":
    # A lógica de parsing de argumentos é mantida, mas o nome do script e a descrição são atualizados
    parser = argparse.ArgumentParser(
        description="Limpa a tabela 'trades' de um ambiente específico no banco de dados PostgreSQL."
    )
    # O argumento agora é posicional para corresponder à chamada em run.py
    parser.add_argument(
        'environment',
        type=str,
        choices=['trade', 'test', 'backtest'],
        help='O ambiente de execução para limpar (trade, test, backtest).'
    )
    args = parser.parse_args()

    main(environment=args.environment)
