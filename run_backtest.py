# run_backtest.py

import pandas as pd
from src.core.backtester import Backtester
from src.logger import logger

def main():
    logger.info("--- INICIANDO PROCESSO DE BACKTEST ---")

    # Carrega a tabela mestre, que contém todos os dados e features
    # NOTA: O ideal é ter a tabela salva em um formato mais rápido como Parquet ou Feather.
    try:
        # Substitua 'features_master_table.csv' pelo caminho real se for diferente
        master_table_path = "data/features_master_table.csv" 
        df = pd.read_csv(master_table_path, index_col='timestamp', parse_dates=True)
        logger.info(f"Tabela mestre carregada com {len(df)} registros.")
    except FileNotFoundError:
        logger.error(f"ERRO: A tabela mestre '{master_table_path}' não foi encontrada.")
        logger.error("Por favor, execute o data_pipeline.py primeiro para gerar os dados.")
        return

    # Instancia e executa o backtester
    backtester = Backtester(data=df)
    backtester.run()

if __name__ == "__main__":
    main()