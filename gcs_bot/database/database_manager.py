# src/database_manager.py (VERSÃO FINAL COMPATÍVEL)

import json
import numpy as np
import pandas as pd
from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS
from gcs_bot.utils.config_manager import settings
from gcs_bot.utils.logger import logger

class DatabaseManager:
    def __init__(self):
        self.url = settings.database.url
        self.token = settings.database.token
        self.org = settings.database.org
        self.bucket = settings.database.bucket
        self._client = InfluxDBClient(url=self.url, token=self.token, org=self.org, timeout=30_000)
        # Mantemos os métodos antigos para não quebrar o data_pipeline
        self.query_api = self._client.query_api()
        self.write_api = self._client.write_api(write_options=SYNCHRONOUS)

    def get_write_api(self): # Função mantida para compatibilidade
        return self.write_api

    def get_query_api(self): # Função mantida para compatibilidade
        return self.query_api

    def write_trade(self, trade_data: dict):
        """Escreve um único registo de trade no InfluxDB."""
        try:
            # Extrai a confiança final para ser guardada como um campo numérico separado
            final_confidence = trade_data.get("decision_data", {}).get("final_confidence", 0.0)

            point = Point("trades") \
                .tag("status", trade_data["status"]) \
                .tag("trade_id", trade_data["trade_id"]) \
                .field("entry_price", float(trade_data["entry_price"])) \
                .field("profit_target_price", float(trade_data.get("profit_target_price", 0.0))) \
                .field("stop_loss_price", float(trade_data.get("stop_loss_price", 0.0))) \
                .field("quantity_btc", float(trade_data.get("quantity_btc", 0.0))) \
                .field("realized_pnl_usdt", float(trade_data.get("realized_pnl_usdt", 0.0))) \
                .field("final_confidence", float(final_confidence)) \
                .field("decision_data", json.dumps(trade_data.get("decision_data", {}))) \
                .time(trade_data["timestamp"])
            
            self.write_api.write(bucket=self.bucket, org=self.org, record=point)
            logger.info(f"Trade {trade_data['trade_id']} escrito no DB com status {trade_data['status']}.")
        except Exception as e:
            logger.error(f"Falha ao escrever trade no DB: {e}", exc_info=True)

    def get_open_positions(self) -> pd.DataFrame:
        try:
            query = f'''
            from(bucket: "{self.bucket}")
                |> range(start: -30d) 
                |> filter(fn: (r) => r._measurement == "trades")
                |> filter(fn: (r) => r.status == "OPEN")
                |> pivot(rowKey:["_time"], columnKey: ["_field"], valueColumn: "_value")
                |> sort(columns: ["_time"], desc: false)
            '''
            df = self.query_api.query_data_frame(query, org=self.org)
            if isinstance(df, list): df = pd.concat(df, ignore_index=True) if df else pd.DataFrame()
            if df.empty: return pd.DataFrame()
            
            df = df.rename(columns={"_time": "timestamp"})
            cols_to_drop = ['result', 'table', '_start', '_stop', '_measurement', 'status']
            df.drop(columns=[col for col in cols_to_drop if col in df.columns], inplace=True, errors='ignore')

            # Garante que as colunas numéricas são do tipo correto
            numeric_cols = ['entry_price', 'profit_target_price', 'stop_loss_price', 'quantity_btc', 'realized_pnl_usdt', 'final_confidence']
            for col in numeric_cols:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce')

            # Converte a coluna 'decision_data' de string JSON para dict
            if 'decision_data' in df.columns:
                def safe_json_loads(s):
                    if isinstance(s, str):
                        try:
                            return json.loads(s)
                        except json.JSONDecodeError:
                            # Loga um aviso se a string não for um JSON válido
                            logger.warning(f"Não foi possível decodificar o JSON em decision_data: '{s}'")
                            return {}
                    return {} # Retorna um dict vazio se não for uma string (ex: NaN)

                df['decision_data'] = df['decision_data'].apply(safe_json_loads)

            df.set_index('trade_id', inplace=True)
            return df
        except Exception as e:
            logger.error(f"Falha ao buscar posições abertas do DB: {e}", exc_info=True)
            return pd.DataFrame()

    def get_all_trades_in_range(self, start_date: str = "-90d", end_date: str = "now()"):
        """Busca todos os trades (abertos e fechados) em um determinado período."""
        try:
            logger.info(f"Buscando todos os trades de {start_date} a {end_date}...")
            query = f'''
            from(bucket: "{self.bucket}")
                |> range(start: {start_date}, stop: {end_date})
                |> filter(fn: (r) => r._measurement == "trades")
                |> pivot(rowKey:["_time"], columnKey: ["_field"], valueColumn: "_value")
                |> sort(columns: ["_time"], desc: false)
            '''
            df = self.query_api.query_data_frame(query, org=self.org)
            if isinstance(df, list):
                df = pd.concat(df, ignore_index=True) if df else pd.DataFrame()
            if df.empty:
                logger.warning("Nenhum trade encontrado no período especificado.")
                return pd.DataFrame()

            df = df.rename(columns={"_time": "timestamp"})
            cols_to_drop = ['result', 'table', '_start', '_stop', '_measurement']
            df.drop(columns=[col for col in cols_to_drop if col in df.columns], inplace=True, errors='ignore')

            # Converte colunas numéricas
            numeric_cols = ['entry_price', 'profit_target_price', 'stop_loss_price', 'quantity_btc', 'realized_pnl_usdt', 'final_confidence']
            for col in numeric_cols:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce')

            return df
        except Exception as e:
            logger.error(f"Falha ao buscar todos os trades do DB: {e}", exc_info=True)
            return pd.DataFrame()

    def get_last_n_trades(self, n: int):
        """Busca os últimos N trades com status 'CLOSED' para análise de performance."""
        try:
            # --- INÍCIO DA CORREÇÃO ---
            # Adicionada a função pivot() no final, como sugerido pelo warning.
            query = f'''
            from(bucket: "{self.bucket}")
                |> range(start: -90d)
                |> filter(fn: (r) => r._measurement == "trades")
                |> filter(fn: (r) => r.status == "CLOSED")
                |> filter(fn: (r) => r._field == "realized_pnl_usdt")
                |> sort(columns: ["_time"], desc: true)
                |> limit(n: {n})
                |> pivot(rowKey:["_time"], columnKey: ["_field"], valueColumn: "_value")
            '''
            # --- FIM DA CORREÇÃO ---
            df = self.query_api.query_data_frame(query, org=self.org)
            if isinstance(df, list):
                df = pd.concat(df, ignore_index=True) if df else pd.DataFrame()

            if df.empty:
                return pd.DataFrame()
            
            # Como o pivot() já formata bem as colunas, podemos simplificar o retorno
            df = df.rename(columns={"_time": "timestamp", "realized_pnl_usdt": "pnl"})
            return df[['timestamp', 'pnl']]

        except Exception as e:
            logger.error(f"Falha ao buscar os últimos {n} trades do DB: {e}", exc_info=True)
            return pd.DataFrame()

    def get_all_trades_for_analysis(self, start_date: str = "-90d", end_date: str = "now()"):
        """
        Busca e formata todos os trades para a análise de resultados.
        """
        trades_df = self.get_all_trades_in_range(start_date, end_date)

        if trades_df.empty:
            return pd.DataFrame()

        # Apenas trades fechados são relevantes para a análise de PnL
        trades_df = trades_df[trades_df['status'] == 'CLOSED'].copy()

        # Renomeia colunas para compatibilidade com o script de análise
        trades_df.rename(columns={
            'timestamp': 'entry_time',
            'realized_pnl_usdt': 'pnl'
        }, inplace=True)

        # O 'exit_time' não está disponível diretamente, mas para a análise atual não é usado.
        # Se for necessário, precisaria ser adicionado ao schema do InfluxDB.
        # Por enquanto, criamos uma coluna vazia para manter a estrutura.
        trades_df['exit_time'] = pd.NaT

        # Garante que as colunas necessárias existem
        required_cols = ['entry_time', 'exit_time', 'pnl', 'final_confidence']
        for col in required_cols:
            if col not in trades_df.columns:
                # Adiciona a coluna com valor default se não existir
                if col == 'exit_time':
                     trades_df[col] = pd.NaT
                elif col == 'final_confidence':
                     trades_df[col] = 0.0 # Default para confiança
                else:
                     trades_df[col] = np.nan


        return trades_df[required_cols]

db_manager = DatabaseManager()