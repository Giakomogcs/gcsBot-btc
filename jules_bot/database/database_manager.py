# src/database_manager.py (VERSÃO FINAL COMPATÍVEL)

import json
import uuid
from typing import Optional
import numpy as np
import pandas as pd
from influxdb_client import InfluxDBClient, Point
from datetime import datetime, timezone
from influxdb_client.client.write_api import SYNCHRONOUS
from jules_bot.utils.config_manager import settings
from jules_bot.utils.logger import logger

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

    def is_measurement_empty(self, measurement: str) -> bool:
        """Verifica se uma measurement no InfluxDB está vazia."""
        try:
            query = f'''
            from(bucket: "{self.bucket}")
                |> range(start: -100y)
                |> filter(fn: (r) => r._measurement == "{measurement}")
                |> limit(n: 1)
            '''
            result = self.query_api.query(query, org=self.org)
            return len(result) == 0
        except Exception as e:
            logger.error(f"Falha ao verificar se a measurement '{measurement}' está vazia: {e}", exc_info=True)
            return True # Assume que está vazia em caso de erro, para forçar o bootstrap

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

            # Converte a string JSON de decision_data para um dicionário
            if 'decision_data' in df.columns:
                df['decision_data'] = df['decision_data'].apply(lambda x: json.loads(x) if isinstance(x, str) else x)

            df.set_index('trade_id', inplace=True)
            return df
        except Exception as e:
            logger.error(f"Falha ao buscar posições abertas do DB: {e}", exc_info=True)
            return pd.DataFrame()

    def get_trade_by_id(self, trade_id: str) -> Optional[pd.Series]:
        """Busca um único trade pelo seu trade_id."""
        try:
            # Uma consulta mais direcionada para buscar o estado mais recente de um único trade.
            query = f'''
            from(bucket: "{self.bucket}")
                |> range(start: -90d) // Range amplo para garantir que encontramos o trade
                |> filter(fn: (r) => r._measurement == "trades")
                |> filter(fn: (r) => r.trade_id == "{trade_id}")
                |> sort(columns: ["_time"], desc: true) // Pega o registro mais recente para esse ID
                |> limit(n: 1)
                |> pivot(rowKey:["_time"], columnKey: ["_field"], valueColumn: "_value")
            '''
            df = self.query_api.query_data_frame(query, org=self.org)
            if isinstance(df, list): df = pd.concat(df, ignore_index=True) if df else pd.DataFrame()
            if df.empty:
                logger.warning(f"Nenhum trade encontrado com o ID: {trade_id}")
                return None

            # Renomeia e limpa colunas
            df = df.rename(columns={"_time": "timestamp"})
            cols_to_drop = ['result', 'table', '_start', '_stop', '_measurement', 'trade_id'] # trade_id já temos
            df.drop(columns=[col for col in cols_to_drop if col in df.columns], inplace=True, errors='ignore')

            # Garante tipos numéricos corretos
            numeric_cols = ['entry_price', 'profit_target_price', 'stop_loss_price', 'quantity_btc', 'realized_pnl_usdt', 'final_confidence']
            for col in numeric_cols:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce')

            # Desserializa o JSON de decision_data
            if 'decision_data' in df.columns and isinstance(df['decision_data'].iloc[0], str):
                df['decision_data'] = df['decision_data'].apply(json.loads)

            # Retorna a primeira (e única) linha como uma Series
            trade_series = df.iloc[0]
            trade_series.name = trade_id # Define o nome da Series como o trade_id
            return trade_series

        except Exception as e:
            logger.error(f"Falha ao buscar trade pelo ID '{trade_id}': {e}", exc_info=True)
            return None

    def set_legacy_hold(self, trade_id: str, status: str, is_legacy: bool):
        """Sets the is_legacy_hold flag for a specific trade."""
        try:
            point = Point("trades") \
                .tag("trade_id", trade_id) \
                .tag("status", status) \
                .field("is_legacy_hold", is_legacy) \
                .time(datetime.now(timezone.utc))

            self.write_api.write(bucket=self.bucket, org=self.org, record=point)
            logger.info(f"Trade {trade_id} marked as legacy hold: {is_legacy}.")
        except Exception as e:
            logger.error(f"Falha ao marcar trade {trade_id} como legacy hold: {e}", exc_info=True)

    def execute_90_10_take_profit_split(self, original_position: pd.Series, treasury_quantity: float, realized_pnl: float):
        """
        Atomically closes 90% of a position and creates a new 10% "treasured" position
        by writing two points to InfluxDB in a single batch.
        """
        try:
            now = datetime.now(timezone.utc)

            # Ponto 1: Atualiza a posição original para 'CLOSED'
            # Escrevemos todos os campos para garantir a consistência do último estado.
            # A quantidade é zerada para indicar que a parte 'ativa' do trade acabou.
            closed_point = Point("trades") \
                .tag("trade_id", original_position.name) \
                .tag("status", "CLOSED") \
                .field("entry_price", float(original_position.get('entry_price', 0.0))) \
                .field("quantity_btc", 0.0) \
                .field("realized_pnl_usdt", float(original_position.get('realized_pnl_usdt', 0.0)) + realized_pnl) \
                .field("profit_target_price", float(original_position.get('profit_target_price', 0.0))) \
                .field("stop_loss_price", float(original_position.get('stop_loss_price', 0.0))) \
                .field("is_legacy_hold", bool(original_position.get('is_legacy_hold', False))) \
                .time(now)

            # Ponto 2: Cria a nova posição "do tesouro"
            treasured_point = Point("trades") \
                .tag("trade_id", str(uuid.uuid4())) \
                .tag("status", "TREASURED") \
                .field("entry_price", float(original_position.get('entry_price', 0.0))) \
                .field("quantity_btc", treasury_quantity) \
                .field("realized_pnl_usdt", 0.0) \
                .field("is_legacy_hold", False) \
                .time(now)

            # Escreve os dois pontos como um lote único para garantir a atomicidade
            self.write_api.write(bucket=self.bucket, org=self.org, record=[closed_point, treasured_point])

            logger.info(f"90/10 split executado com sucesso para o trade original {original_position.name}.")
            return True

        except Exception as e:
            logger.error(f"CRÍTICO: A transação de split 90/10 falhou para o trade {original_position.name}. Erro: {e}", exc_info=True)
            return False

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

            # Converte a string JSON de decision_data para um dicionário
            if 'decision_data' in df.columns:
                df['decision_data'] = df['decision_data'].apply(lambda x: json.loads(x) if isinstance(x, str) else x)

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