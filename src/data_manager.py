# Ficheiro: src/core/data_manager.py

import pandas as pd
from binance.client import Client
from src.logger import logger
from src.config_manager import settings
from src.database_manager import db_manager

class DataManager:
    """
    Gerencia a LEITURA da tabela mestre de features já processada pelo pipeline.
    """
    def __init__(self) -> None:
        pass # A inicialização do cliente já não é necessária aqui.

    def get_feature_dataframe(self) -> pd.DataFrame:
        """
        Lê a tabela mestre de features do InfluxDB.
        """
        measurement_name = "features_master_table"
        query_api = db_manager.get_query_api()
        if not query_api:
            logger.error("API de consulta do InfluxDB indisponível.")
            return pd.DataFrame()
        logger.info(f"Lendo a tabela mestre de features '{measurement_name}'...")
        try:
            query = f'from(bucket:"{settings.influxdb_bucket}") |> range(start: -10y) |> filter(fn: (r) => r._measurement == "{measurement_name}") |> pivot(rowKey:["_time"], columnKey: ["_field"], valueColumn: "_value")'
            df = query_api.query_data_frame(query)
            if df.empty:
                logger.error(f"Nenhum dado retornado da tabela mestre. Execute o pipeline de ingestão primeiro ('./manage.ps1 update-db').")
                return pd.DataFrame()
            df = df.rename(columns={"_time": "timestamp"})
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            df = df.set_index('timestamp')
            cols_to_drop = ['result', 'table']
            df = df.drop(columns=[col for col in cols_to_drop if col in df.columns])
            logger.info(f"✅ {len(df)} registos lidos da tabela mestre com sucesso.")
            return df
        except Exception as e:
            logger.error(f"❌ Erro ao ler a tabela mestre do InfluxDB: {e}", exc_info=True)
            return pd.DataFrame()

    def run_data_pipeline(self, **kwargs):
        """
        Esta função foi depreciada nesta classe.
        A lógica de ingestão agora vive em 'scripts/data_pipeline.py'.
        Este método agora simplesmente lê a tabela de features final.
        """
        logger.info("--- 🚀 LENDO TABELA DE FEATURES PRÉ-PROCESSADA 🚀 ---")
        return self.get_feature_dataframe()