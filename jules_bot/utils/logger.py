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
        return json.dumps(log_object, ensure_ascii=False)

# --- CONFIGURAÇÃO DO LOGGER ---
# The config_manager is now initialized in main.py before this module is imported.
# We can safely use it to get the bot_name.
from jules_bot.utils.config_manager import config_manager

# Get bot name and mode for log isolation
bot_name = config_manager.bot_name
if not bot_name:
    # This case can happen if a script imports the logger without initializing
    # the config_manager first. We fall back to a default name to avoid crashing.
    bot_name = "unknown_bot"

bot_mode = os.getenv("BOT_MODE", "main")  # 'main' as default for scripts without a mode

# Create a unique logger name for each bot instance and mode
logger_name = f"gcsBot.{bot_name}.{bot_mode}"
logger = logging.getLogger(logger_name)
logger.setLevel(logging.DEBUG)
logger.propagate = False # Impede que os logs sejam passados para o logger root

# Como não estamos mais logando para arquivos, só precisamos de um handler de console.
# Este handler enviará logs para o stderr, que é o que o 'docker logs' captura.
if not logger.handlers:
    json_formatter = JsonFormatter()

    # Handler para o CONSOLE
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setFormatter(json_formatter)
    # Define o nível para DEBUG para capturar tudo.
    console_handler.setLevel(logging.DEBUG)
    logger.addHandler(console_handler)

    logger.info(f"Logger configurado para output de console (stderr). Logger Name: '{logger_name}'")

def log_table(title, data, headers="keys", tablefmt="heavy_grid"):
    """Helper function to log tabular data using the correct logger instance."""
    try:
        is_empty = False
        if isinstance(data, pd.DataFrame): is_empty = data.empty
        elif isinstance(data, list): is_empty = not data
        elif data is None: is_empty = True

        if is_empty:
            logger.info(f"\n--- {title} ---\n(Sem dados para exibir)")
            return
        
        table = tabulate(data, headers=headers, tablefmt=tablefmt, stralign="right", numalign="right")
        # Use the already configured logger instance
        logger.info(f"\n--- {title} ---\n{table}")
    except Exception as e:
        # Use the already configured logger instance
        logger.error(f"Erro ao gerar a tabela '{title}': {e}")
