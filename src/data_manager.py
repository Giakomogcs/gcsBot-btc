# src/data_manager.py

import pandas as pd
import influxdb_client
from influxdb_client.client.write_api import SYNCHRONOUS

# Resolução de Path (assumindo que você o queira aqui também)
import sys
import os
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.config_manager import settings
from src.logger import logger

class DataManager:
    def __init__(self):
        try:
            self.client = influxdb_client.InfluxDBClient(
                url=settings.database.url,
                token=settings.database.token,
                org=settings.database.org,
                timeout=300_000 
            )
            self.query_api = self.client.query_api()
            logger.info("Conexão com o InfluxDB estabelecida com sucesso.")
        except Exception as e:
            logger.error(f"Falha ao conectar com o InfluxDB: {e}")
            self.client = None
            self.query_api = None

    def read_data_from_influx(self, measurement: str, start_date: str, end_date: str = "now()") -> pd.DataFrame:
        """
        Lê dados de uma 'measurement' específica do InfluxDB.

        Args:
            measurement (str): O nome da tabela/measurement a ser consultada.
            start_date (str): O início do intervalo de tempo (ex: "-1y", "-180d").
            end_date (str, optional): O fim do intervalo de tempo. Padrão "now()".

        Returns:
            pd.DataFrame: Um DataFrame com os dados solicitados, indexado por tempo e
                          com o fuso horário correto (UTC), ou um DataFrame vazio se
                          nenhum dado for encontrado ou ocorrer um erro.
        """
        if not self.query_api:
            logger.error("Cliente InfluxDB não inicializado. Leitura abortada.")
            return pd.DataFrame()
        
        flux_query = f'''
            from(bucket:"{settings.database.bucket}") 
                |> range(start: {start_date}, stop: {end_date}) 
                |> filter(fn: (r) => r._measurement == "{measurement}") 
                |> pivot(rowKey:["_time"], columnKey: ["_field"], valueColumn: "_value")
            '''

        try:
            logger.info(f"Executando query na measurement '{measurement}' de {start_date} até {end_date}...")
            result = self.query_api.query_data_frame(query=flux_query)

            if result.empty:
                logger.warning(f"Nenhum dado encontrado para a measurement '{measurement}' no período especificado.")
                return pd.DataFrame()

            # Limpeza e formatação do DataFrame
            df = result.copy()
            df.rename(columns={'_time': 'timestamp'}, inplace=True)
            df.set_index('timestamp', inplace=True)
            df = df.drop(columns=['result', 'table', '_start', '_stop', '_measurement'], errors='ignore')
            
            # Garante que o índice é do tipo datetime e está em UTC
            if not pd.api.types.is_datetime64_any_dtype(df.index):
                 df.index = pd.to_datetime(df.index)
            
            if df.index.tz is None:
                df = df.tz_localize('UTC')
            else:
                df = df.tz_convert('UTC')

            df = df.sort_index()
            
            logger.info(f"{len(df)} registros carregados da measurement '{measurement}'.")
            return df

        except Exception as e:
            logger.error(f"Erro ao executar a query no InfluxDB para '{measurement}': {e}")
            return pd.DataFrame()

    def __del__(self):
        """
        Fecha o cliente InfluxDB ao destruir o objeto.
        """
        if self.client:
            self.client.close()
            logger.info("Conexão com o InfluxDB fechada.")