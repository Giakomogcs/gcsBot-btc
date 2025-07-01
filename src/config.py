# src/config.py

from dotenv import load_dotenv
import os
from src.logger import logger

# Carrega as variáveis do arquivo .env para o ambiente
load_dotenv()

def get_config_var(var_name, default_value=None):
    """
    Função auxiliar para ler uma variável de ambiente e limpá-la.
    Remove espaços em branco e aspas simples/duplas.
    """
    value = os.getenv(var_name, default_value)
    if isinstance(value, str):
        # Remove espaços no início/fim e remove aspas
        return value.strip().strip("'\"")
    return value

# --- MODO DE OPERAÇÃO ---
MODE = get_config_var("MODE", "optimize").lower()

# --- CONFIGURAÇÕES DA BINANCE ---
SYMBOL = get_config_var("SYMBOL", "BTCUSDT").upper()
USE_TESTNET = (MODE == 'test')

# Seleciona as chaves de API corretas com base no modo de operação
API_KEY = get_config_var("BINANCE_TESTNET_API_KEY") if USE_TESTNET else get_config_var("BINANCE_API_KEY")
API_SECRET = get_config_var("BINANCE_TESTNET_API_SECRET") if USE_TESTNET else get_config_var("BINANCE_API_SECRET")

# Validação crítica das chaves de API
if MODE in ['test', 'trade'] and (not API_KEY or not API_SECRET):
    raise ValueError(f"Para MODE='{MODE}', as chaves da API correspondentes devem ser configuradas no .env")

# --- ESTRATÉGIA DE GESTÃO DE PORTFÓLIO E RISCO ---
# O MÁXIMO de capital em USDT que este bot tem permissão para gerenciar.
# O bot usará o menor valor entre este e o seu saldo real na Binance.
# Defina um valor alto (ex: 1000000) se quiser que ele use sempre 100% do seu saldo.
MAX_USDT_ALLOCATION = float(get_config_var("MAX_USDT_ALLOCATION", 1000.0))

# Percentual do capital que será usado para comprar e manter BTC como holding de longo prazo.
# O bot NÃO tocará nesta parte do BTC para fazer trades. Ex: 0.50 = 50%
LONG_TERM_HOLD_PCT = float(get_config_var("LONG_TERM_HOLD_PCT", 0.50))

# Do capital de TRADING restante, qual a % de risco por operação? Este é o seu principal controle.
# Ex: 0.02 = 2% do capital de trading será arriscado em cada nova operação.
RISK_PER_TRADE_PCT = float(get_config_var("RISK_PER_TRADE_PCT", 0.02))

# --- CONFIGURAÇÕES DE ARQUIVOS ---
DATA_DIR = "data"
LOGS_DIR = "logs"
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)

KAGGLE_BOOTSTRAP_FILE = os.path.join(DATA_DIR, "kaggle_btc_1m_bootstrap.csv")
HISTORICAL_DATA_FILE = os.path.join(DATA_DIR, f"full_historical_{SYMBOL}.csv")
MODEL_FILE = os.path.join(DATA_DIR, "trading_model.pkl")
SCALER_FILE = os.path.join(DATA_DIR, "scaler.pkl")
TRADES_LOG_FILE = os.path.join(DATA_DIR, "trades_log.csv")
BOT_STATE_FILE = os.path.join(DATA_DIR, "bot_state.json")
WFO_STATE_FILE = os.path.join(DATA_DIR, "wfo_optimization_state.json")
STRATEGY_PARAMS_FILE = os.path.join(DATA_DIR, "strategy_params.json")

# --- PARÂMETROS PARA A OTIMIZAÇÃO WALK-FORWARD ---
WFO_TRAIN_MINUTES = int(get_config_var("WFO_TRAIN_MINUTES", 43200)) # ~30 dias
WFO_TEST_MINUTES = int(get_config_var("WFO_TEST_MINUTES", 10080))  # ~7 dias
WFO_STEP_MINUTES = int(get_config_var("WFO_STEP_MINUTES", 10080))  # ~7 dias

FORCE_OFFLINE_MODE = get_config_var("FORCE_OFFLINE_MODE", False)