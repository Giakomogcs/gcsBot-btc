# src/config.py (VERSÃO 5.0 - ARQUITETURA DE ESPECIALISTAS)

from dotenv import load_dotenv
import os
import sys

# Carrega as variáveis do arquivo .env para o ambiente
load_dotenv()

def get_config_var(var_name, default_value=None):
    """Função auxiliar para ler uma variável de ambiente e limpá-la."""
    value = os.getenv(var_name, default_value)
    if isinstance(value, str):
        return value.strip().strip("'\"")
    return value

# --- MODO DE OPERAÇÃO ---
MODE = get_config_var("MODE", "optimize").lower()
FORCE_OFFLINE_MODE = get_config_var("FORCE_OFFLINE_MODE", "False").lower() == 'true'

# --- CONFIGURAÇÕES DA BINANCE ---
SYMBOL = get_config_var("SYMBOL", "BTCUSDT").upper()
USE_TESTNET = (MODE == 'test')
API_KEY = get_config_var("BINANCE_TESTNET_API_KEY") if USE_TESTNET else get_config_var("BINANCE_API_KEY")
API_SECRET = get_config_var("BINANCE_TESTNET_API_SECRET") if USE_TESTNET else get_config_var("BINANCE_API_SECRET")

# --- PARÂMETROS GERAIS DA ESTRATÉGIA ---
MAX_USDT_ALLOCATION = float(get_config_var("MAX_USDT_ALLOCATION", 1000.0))
FEE_RATE = float(get_config_var("FEE_RATE", 0.001))
SLIPPAGE_RATE = float(get_config_var("SLIPPAGE_RATE", 0.0005))

# --- CONFIGURAÇÕES DE DIRETÓRIOS E ARQUIVOS ---
DATA_DIR = "data"
LOGS_DIR = "logs"
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)

# Arquivos de dados brutos e de estado
KAGGLE_BOOTSTRAP_FILE = os.path.join(DATA_DIR, "kaggle_btc_1m_bootstrap.csv")
HISTORICAL_DATA_FILE = os.path.join(DATA_DIR, f"full_historical_{SYMBOL}.csv")
COMBINED_DATA_CACHE_FILE = os.path.join(DATA_DIR, "combined_data_cache.csv")
TRADES_LOG_FILE = os.path.join(DATA_DIR, "trades_log.csv")
BOT_STATE_FILE = os.path.join(DATA_DIR, "bot_state.json")

### PASSO 2: Remover variáveis obsoletas e centralizar a verdade nos metadados ###
# As variáveis MODEL_FILE, SCALER_FILE e STRATEGY_PARAMS_FILE foram removidas.
# O sistema agora usa múltiplos especialistas, e o arquivo de metadados
# atua como um "manifesto" para localizar todos os artefatos necessários.
MODEL_METADATA_FILE = os.path.join(DATA_DIR, "model_metadata.json")

# --- PARÂMETROS PARA A OTIMIZAÇÃO ---
WFO_TRAIN_MINUTES = int(get_config_var("WFO_TRAIN_MINUTES", 788400)) # ~18 meses para ter dados de vários regimes
MODEL_VALIDITY_MONTHS = int(get_config_var("MODEL_VALIDITY_MONTHS", 3))
QUICK_OPTIMIZE = get_config_var("QUICK_OPTIMIZE", "False").lower() == 'true'

# --- PARÂMETROS PARA O MODO DE BACKTEST RÁPIDO ---
BACKTEST_START_DATE = get_config_var("BACKTEST_START_DATE", "2024-01-01")
BACKTEST_END_DATE = get_config_var("BACKTEST_END_DATE", "2025-03-31")

# --- VALIDAÇÕES FINAIS DE SANIDADE ---
if MODE in ['test', 'trade'] and not FORCE_OFFLINE_MODE and (not API_KEY or not API_SECRET):
    # O logger pode não estar pronto, então usamos print/exit para garantir a mensagem.
    sys.exit(f"ERRO DE CONFIGURAÇÃO: Para MODE='{MODE}', as chaves da API da Binance devem ser configuradas no arquivo .env")

if FORCE_OFFLINE_MODE and MODE in ['test', 'trade']:
    sys.exit(f"ERRO DE CONFIGURAÇÃO: O bot não pode rodar em modo '{MODE.upper()}' com 'FORCE_OFFLINE_MODE=True'.")