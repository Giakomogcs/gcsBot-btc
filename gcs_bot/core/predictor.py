# Ficheiro: src/core/predictor.py

import joblib
import pandas as pd
from pathlib import Path

from gcs_bot.utils.logger import logger
from gcs_bot.utils.config_manager import settings
from gcs_bot.database.database_manager import db_manager
from gcs_bot.data.feature_engineering import add_all_features

class Predictor:
    """
    O cérebro preditivo do bot. Carrega o modelo treinado e os dados
    mais recentes para gerar um sinal de trading.
    """
    def __init__(self, model_path: str):
        self.model_path = Path(model_path)
        self.model = self._load_model()
        self.required_features = self._get_model_features()

    def _load_model(self):
        """Carrega o modelo de IA a partir do ficheiro .joblib."""
        try:
            if not self.model_path.exists():
                logger.error(f"Erro Crítico: Ficheiro do modelo não encontrado em '{self.model_path}'")
                logger.error("Execute o otimizador ('./manage.ps1 optimize') para treinar e salvar um modelo primeiro.")
                return None
            
            model = joblib.load(self.model_path)
            logger.info(f"✅ Modelo de IA carregado com sucesso de '{self.model_path}'.")
            return model
        except Exception as e:
            logger.error(f"Falha ao carregar o modelo de '{self.model_path}': {e}", exc_info=True)
            return None

    def _get_model_features(self) -> list:
        """Extrai a lista de features que o modelo espera, se disponível."""
        if self.model and hasattr(self.model, 'feature_names_in_'):
            return self.model.feature_names_in_
        logger.warning("Não foi possível extrair a lista de features do modelo. A verificação de features será limitada.")
        # Se não for possível extrair, retornamos as features do config como fallback
        return settings.trading_strategy.models.specialists.price_action.features

    def _get_latest_data(self) -> pd.DataFrame:
        """Busca os dados mais recentes do InfluxDB para a criação de features."""
        try:
            # Precisamos de um período de "warmup" para calcular os indicadores (ex: 200 para a MA de 200)
            # Buscamos os últimos 300 minutos de dados como uma margem de segurança.
            query = f'''
            from(bucket: "{db_manager.bucket}")
                |> range(start: -300m)
                |> filter(fn: (r) => r._measurement == "btc_btcusdt_1m")
                |> pivot(rowKey:["_time"], columnKey: ["_field"], valueColumn: "_value")
                |> sort(columns: ["_time"], desc: false)
            '''
            df = db_manager.query_api.query_data_frame(query, org=db_manager.org)
            if isinstance(df, list): df = pd.concat(df, ignore_index=True) if df else pd.DataFrame()

            if df.empty or len(df) < 200:
                logger.warning(f"Dados recentes insuficientes no DB para gerar features ({len(df)} pontos).")
                return pd.DataFrame()

            df = df.rename(columns={"_time": "timestamp"})
            df = df.set_index('timestamp')
            
            # Limpa colunas de metadados do InfluxDB
            cols_to_drop = ['result', 'table', '_start', '_stop', '_measurement']
            df.drop(columns=[col for col in cols_to_drop if col in df.columns], inplace=True, errors='ignore')
            
            return df
        except Exception as e:
            logger.error(f"Falha ao buscar dados recentes do DB para previsão: {e}", exc_info=True)
            return pd.DataFrame()

    def generate_signal(self) -> str:
        """
        Orquestra o processo de obtenção de dados, engenharia de features e previsão.
        """
        if not self.model:
            logger.error("Modelo não está carregado. Impossível gerar sinal.")
            return "NEUTRAL"

        # 1. Obter dados brutos
        df_raw = self._get_latest_data()
        if df_raw.empty:
            return "NEUTRAL"

        # 2. Adicionar features
        df_features = add_all_features(df_raw)
        
        # 3. Pegar a última linha, que contém as features mais recentes
        latest_features = df_features.iloc[-1:]
        
        # Garante que todas as colunas que o modelo precisa estão presentes
        missing_cols = [col for col in self.required_features if col not in latest_features.columns]
        if missing_cols:
            logger.error(f"Features em falta para a previsão: {missing_cols}. Impossível gerar sinal.")
            return "NEUTRAL"
            
        X = latest_features[self.required_features]

        # 4. Fazer a previsão
        try:
            prediction = self.model.predict(X)
            probability = self.model.predict_proba(X)
            
            signal = "BUY" if prediction[0] == 1 else "NEUTRAL"
            confidence = probability[0][1] if signal == "BUY" else 1 - probability[0][1]
            
            logger.info(f"Previsão do Modelo: Sinal='{signal}', Confiança={confidence:.2%}")

            # 5. Aplicar o limiar de confiança
            if signal == "BUY" and confidence >= settings.trading_strategy.confidence_threshold:
                return "BUY"
            
            return "NEUTRAL"

        except Exception as e:
            logger.error(f"Erro durante a previsão do modelo: {e}", exc_info=True)
            return "NEUTRAL"