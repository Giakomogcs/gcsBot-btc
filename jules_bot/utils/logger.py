# src/logger.py (VERSÃO 5.2 - ISOLAMENTO DE LOGS)

import logging
import json
import sys
import os
from tabulate import tabulate
import pandas as pd
from datetime import datetime
import pytz

# --- NÍVEL DE LOG CUSTOMIZADO PARA PERFORMANCE ---
PERFORMANCE_LEVEL_NUM = 25
logging.addLevelName(PERFORMANCE_LEVEL_NUM, "PERFORMANCE")

def performance(self, message, *args, **kws):
    if self.isEnabledFor(PERFORMANCE_LEVEL_NUM):
        self._log(PERFORMANCE_LEVEL_NUM, message, args, **kws)

logging.Logger.performance = performance

# --- FORMATADOR JSON CUSTOMIZADO ---
class JsonFormatter(logging.Formatter):
    _timezone = pytz.timezone('America/Sao_Paulo')

    def formatTime(self, record, datefmt=None):
        dt = datetime.fromtimestamp(record.created, tz=pytz.utc).astimezone(self._timezone)
        if datefmt:
            return dt.strftime(datefmt)

        # This format is what the user's log shows, so let's stick to it.
        # YYYY-MM-DD HH:MM:SS,ms
        t = dt.strftime('%Y-%m-%d %H:%M:%S')
        return '%s,%03d' % (t, record.msecs)

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
# Get bot name from environment variable for log isolation
bot_name = os.getenv("BOT_NAME", "jules_bot")

logger = logging.getLogger(f"gcsBot.{bot_name}")
logger.setLevel(logging.DEBUG)
logger.propagate = False # Impede que os logs sejam passados para o logger root

# Como não estamos mais logando para arquivos, só precisamos de um handler de console.
# Este handler enviará logs para o stderr, que é o que o 'docker logs' captura.
if not logger.handlers:
    json_formatter = JsonFormatter()

    # Handler para o CONSOLE
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setFormatter(json_formatter)
    # Define o nível para DEBUG para capturar tudo. O controle de verbosidade
    # pode ser feito no ambiente de visualização, se necessário.
    console_handler.setLevel(logging.DEBUG)
    logger.addHandler(console_handler)

    logger.info(f"Logger configurado para output de console (stderr). Bot: {bot_name}")

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
        logging.getLogger(f"gcsBot.{bot_name}").info(f"\n--- {title} ---\n{table}")
    except Exception as e:
        logging.getLogger(f"gcsBot.{bot_name}").error(f"Erro ao gerar a tabela '{title}': {e}")
