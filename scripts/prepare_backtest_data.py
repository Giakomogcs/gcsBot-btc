import sys
import os

# Adiciona a raiz do projeto ao path para permitir a importação de módulos
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from collectors.core_price_collector import prepare_backtest_data
from jules_bot.utils.logger import logger

def main():
    """
    Ponto de entrada para o script de preparação de dados de backtest.
    Espera um argumento da linha de comando para o número de dias.
    """
    if len(sys.argv) < 2:
        logger.error("Erro: Número de dias para preparação não fornecido.")
        logger.error("Uso: python scripts/prepare_backtest_data.py <numero_de_dias>")
        sys.exit(1)

    try:
        days = int(sys.argv[1])
        logger.info(f"Iniciando preparação de dados de backtest para os últimos {days} dias...")
        prepare_backtest_data(days)
        logger.info("✅ Preparação de dados de backtest concluída com sucesso.")
    except ValueError:
        logger.error(f"Erro: O argumento '{sys.argv[1]}' não é um número inteiro válido.")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Ocorreu um erro inesperado durante a preparação dos dados: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()
