import yaml
from pathlib import Path
from typing import Any
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# --- Modelos para o config.yml ---
class AppConfig(BaseModel):
    use_testnet: bool
    force_offline_mode: bool

class DataPathsConfig(BaseModel):
    macro_data_dir: str
    historical_data_file: str
    kaggle_bootstrap_file: str
    models_dir: str

class TargetConfig(BaseModel):
    future_periods: int
    profit_mult: float
    stop_mult: float

class DataPipelineConfig(BaseModel):
    start_date_ingestion: str
    regime_features: list[str]
    tags_for_master_table: list[str]
    target: TargetConfig

class SpecialistConfig(BaseModel):
    features: list[str]

class ModelsConfig(BaseModel):
    specialists: dict[str, SpecialistConfig]

class TripleBarrierConfig(BaseModel):
    profit_mult: float
    stop_mult: float
    time_limit_candles: int

class TradingStrategyConfig(BaseModel):
    confidence_threshold: float
    triple_barrier: TripleBarrierConfig
    models: ModelsConfig
    ensemble_weights: dict[str, float]

class PositionSizingConfig(BaseModel):
    method: str
    risk_per_trade: float

class OptimizerConfig(BaseModel):
    n_trials: int
    quality_threshold: float
    objective_metric: str

class LoggingConfig(BaseModel):
    level: str
    
class BacktestConfig(BaseModel):
    start_date: str
    initial_capital: int
    commission_rate: float

# --- Modelos para Variáveis de Ambiente (.env) ---
class InfluxDBConfig(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')
    url: str = Field(..., alias='INFLUXDB_URL')
    token: str = Field(..., alias='INFLUXDB_TOKEN')
    org: str = Field(..., alias='INFLUXDB_ORG')
    bucket: str = Field(..., alias='INFLUXDB_BUCKET')

class ApiKeysConfig(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')
    binance_api_key: str = Field("", alias='BINANCE_API_KEY')
    binance_api_secret: str = Field("", alias='BINANCE_API_SECRET')
    binance_testnet_api_key: str = Field("", alias='BINANCE_TESTNET_API_KEY')
    binance_testnet_api_secret: str = Field("", alias='BINANCE_TESTNET_API_SECRET')

# --- Classe de Configuração Principal ---
class Settings(BaseSettings):
    database: InfluxDBConfig = InfluxDBConfig()
    api_keys: ApiKeysConfig = ApiKeysConfig()
    
    app: AppConfig
    data_paths: DataPathsConfig
    data_pipeline: DataPipelineConfig
    trading_strategy: TradingStrategyConfig
    position_sizing: PositionSizingConfig
    optimizer: OptimizerConfig
    logging: LoggingConfig
    backtest: BacktestConfig # <-- ADICIONADO O CAMPO QUE FALTAVA

    @classmethod
    def settings_customise_sources(
        cls, settings_cls, init_settings, env_settings, dotenv_settings, file_secret_settings
    ):
        def yaml_config_source() -> dict[str, Any]:
            yaml_file = Path('config.yml')
            if not yaml_file.is_file():
                raise FileNotFoundError("Ficheiro 'config.yml' não encontrado!")
            return yaml.safe_load(yaml_file.read_text())

        return (yaml_config_source,)

# --- Instância Final ---
settings = Settings()