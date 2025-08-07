# src/logger.py (VERSÃO 5.1 - CORRIGIDO PARA EXIBIR LOGS INFO)

import logging
import json
from logging.handlers import TimedRotatingFileHandler
import sys
import os
from tabulate import tabulate
import pandas as pd

# --- NÍVEL DE LOG CUSTOMIZADO PARA PERFORMANCE ---
PERFORMANCE_LEVEL_NUM = 25
logging.addLevelName(PERFORMANCE_LEVEL_NUM, "PERFORMANCE")

def performance(self, message, *args, **kws):
    if self.isEnabledFor(PERFORMANCE_LEVEL_NUM):
        self._log(PERFORMANCE_LEVEL_NUM, message, args, **kws)

logging.Logger.performance = performance

# --- FORMATADOR JSON CUSTOMIZADO ---
class JsonFormatter(logging.Formatter):
    def format(self, record):
        log_object = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "message": record.getMessage(),
        }
        if hasattr(record, 'extra_data'):
            log_object.update(record.extra_data)
        return json.dumps(log_object)

# --- CONFIGURAÇÃO DO LOGGER ---
LOGS_DIR = "logs"
os.makedirs(LOGS_DIR, exist_ok=True)

logger = logging.getLogger("gcsBot")
logger.setLevel(logging.DEBUG)

if not logger.handlers:
    # 1. Handler para o ARQUIVO DE DEBUG (gcs_bot.log)
    log_file_path = os.path.join(LOGS_DIR, 'jules_bot.log')
    file_handler = TimedRotatingFileHandler(log_file_path, when="midnight", interval=1, backupCount=14, encoding='utf-8')
    file_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(file_formatter)
    file_handler.setLevel(logging.DEBUG)
    logger.addHandler(file_handler)

    # 2. Handler para o CONSOLE
    console_handler = logging.StreamHandler(sys.stdout)
    console_formatter = logging.Formatter('%(levelname)s: %(message)s') # Formato mais limpo
    console_handler.setFormatter(console_formatter)
    console_handler.setLevel(logging.INFO) # Nível INFO para o console para não poluir
    logger.addHandler(console_handler)

    # 3. Handler para o ARQUIVO DE PERFORMANCE (performance.jsonl)
    perf_log_path = os.path.join(LOGS_DIR, 'performance.jsonl')
    perf_handler = logging.FileHandler(perf_log_path, mode='a', encoding='utf-8')
    perf_formatter = JsonFormatter()
    perf_handler.setFormatter(perf_formatter)
    perf_handler.setLevel(PERFORMANCE_LEVEL_NUM)
    logger.addHandler(perf_handler)

    logger.info("Logger configurado. Logs de console a partir do nível INFO.")

def log_table(title, data, headers="keys", tablefmt="heavy_grid"):
    try:
        is_empty = False
        if isinstance(data, pd.DataFrame): is_empty = data.empty
        elif isinstance(data, list): is_empty = not data
        elif data is None: is_empty = True

        if is_empty:
            logger.info(f"\n--- {title} ---\n(Sem dados para exibir)")
            return
        
        table = tabulate(data, headers=headers, tablefmt=tablefmt, stralign="right", numalign="right")
        logging.getLogger("gcsBot").info(f"\n--- {title} ---\n{table}")
    except Exception as e:
        logging.getLogger("gcsBot").error(f"Erro ao gerar a tabela '{title}': {e}")