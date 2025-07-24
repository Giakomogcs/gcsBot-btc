# src/config_manager.py

import os
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from typing import Optional

# --- Modelos de Dados para o arquivo config.yml (sem alteração) ---
class AppConfig(BaseSettings):
    environment: str = "development"
    use_testnet: bool = True
    force_offline_mode: bool = False

# ... (O resto das classes de config - DataPathsConfig, ModelParamsConfig, etc. - continuam iguais) ...
class DataPathsConfig(BaseSettings):
    data_dir: str = "data"
    logs_dir: str = "logs"
    model_metadata_file: str = "data/model_metadata.json"
    historical_data_file: str = "data/btc_historical_data.csv"
    kaggle_bootstrap_file: str = "data/kaggle_bootstrap.csv"

class ModelParamsConfig(BaseSettings):
    future_periods: int = 30
    profit_mult: float = 2.0
    stop_mult: float = 2.0
    model_validity_months: int = 1

class OptimizerConfig(BaseSettings):
    wfo_train_minutes: int = 432000
    n_trials_for_cycle: int = 150
    quality_threshold: float = 0.33

class DcaConfig(BaseSettings):
    enabled: bool = True
    min_capital_usdt: float = 100.0
    daily_amount_usdt: float = 5.0


# --- Classe Principal de Configuração ---
class Settings(BaseSettings):
    """
    Carrega e valida todas as configurações e segredos do projeto.
    """
    # Carrega segredos do arquivo .env
    # A variável de ambiente é o nome em MAIÚSCULAS
    binance_api_key: Optional[str] = Field(None, alias='BINANCE_API_KEY')
    binance_api_secret: Optional[str] = Field(None, alias='BINANCE_API_SECRET')
    binance_testnet_api_key: Optional[str] = Field(None, alias='BINANCE_TESTNET_API_KEY')
    binance_testnet_api_secret: Optional[str] = Field(None, alias='BINANCE_TESTNET_API_SECRET')

    influxdb_url: str = Field(..., alias='INFLUXDB_URL')
    influxdb_token: str = Field(..., alias='INFLUXDB_TOKEN')
    influxdb_org: str = Field(..., alias='INFLUXDB_ORG')
    influxdb_bucket: str = Field(..., alias='INFLUXDB_BUCKET')
 

    # Carrega parâmetros do arquivo config.yml
    # O Pydantic irá procurar por estas seções no YAML
    app: AppConfig = AppConfig()
    data_paths: DataPathsConfig = DataPathsConfig()
    model_params: ModelParamsConfig = ModelParamsConfig()
    optimizer: OptimizerConfig = OptimizerConfig()
    dca: DcaConfig = DcaConfig()

    model_config = SettingsConfigDict(
        env_file='.env',
        env_file_encoding='utf-8',
        case_sensitive=False, # Permite que BINANCE_API_KEY no .env mapeie para binance_api_key
    )

# O resto do ficheiro (`get_settings`, etc.) continua igual
def get_settings() -> Settings:
    """
    Função helper para carregar as configurações uma única vez (singleton).
    """
    # Removido o yaml_file daqui para simplificar, Pydantic agora o lê automaticamente se declarado
    return Settings()

settings = get_settings()