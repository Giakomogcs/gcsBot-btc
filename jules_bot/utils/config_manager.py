import configparser
import os
from pathlib import Path
from typing import Dict, Optional
from dotenv import load_dotenv

class ConfigManager:
    """
    A class to manage loading and accessing configuration from a .ini file.
    It can resolve values from environment variables using the @env/ syntax.
    It also supports temporary overrides for optimization purposes.
    """
    def __init__(self, config_file: Path = Path('config.ini')):
        """
        Initializes the ConfigManager and loads the configuration file.
        Args:
            config_file: The path to the configuration file.
        """
        self.bot_name: Optional[str] = None
        self.overrides: Optional[Dict[str, str]] = None
        # Load environment variables from the specified .env file
        load_dotenv(dotenv_path=os.getenv("ENV_FILE", ".env"))
        self.config = configparser.ConfigParser(interpolation=None)
        if not config_file.exists():
            raise FileNotFoundError(f"Configuration file not found: {config_file}")
        self.config.read(config_file)

    def initialize(self, bot_name: str):
        """
        Initializes the manager with a specific bot name to resolve bot-specific env vars.
        """
        self.bot_name = bot_name

    def apply_overrides(self, override_dict: Dict[str, str]):
        """
        Applies a dictionary of temporary overrides. These take highest precedence.
        """
        self.overrides = override_dict

    def clear_overrides(self):
        """
        Clears any temporary overrides.
        """
        self.overrides = None

    def _resolve_value(self, value: str) -> Optional[str]:
        """
        Resolves a value from an environment variable if it starts with @env/.
        If a bot_name is set, it first tries to resolve a bot-specific env var.
        """
        if not isinstance(value, str) or not value.startswith('@env/'):
            return value

        env_var_name = value[5:]
        env_var_value = None

        # 1. Try to get bot-specific environment variable first
        if self.bot_name:
            # e.g., GCS-BOT_BINANCE_API_KEY -> GCS_BOT_BINANCE_API_KEY
            # Normalize bot name to uppercase, replacing hyphens with underscores.
            normalized_bot_name = self.bot_name.upper().replace("-", "_")
            bot_specific_env_var = f"{normalized_bot_name}_{env_var_name}"
            env_var_value = os.getenv(bot_specific_env_var)

        # 2. If not found, fall back to the generic environment variable
        if env_var_value is None:
            env_var_value = os.getenv(env_var_name)

        # Special case for POSTGRES_HOST: if running locally (not in Docker),
        # and the host is set to 'postgres', override to 'localhost'.
        if env_var_name == 'POSTGRES_HOST':
            # A simple way to check if we're not in a Docker container.
            # This works for Linux-based Docker containers.
            is_running_locally = not os.path.exists('/.dockerenv')

            if is_running_locally and (env_var_value == 'postgres' or env_var_value is None):
                return 'localhost'

        return env_var_value

    def get_section(self, section: str) -> Dict[str, str]:
        """
        Retrieves a section from the configuration as a dictionary, resolving env vars.
        """
        if self.config.has_section(section):
            section_items = self.config.items(section)
            return {key: self._resolve_value(value) for key, value in section_items}
        return {}

    def has_section(self, section: str) -> bool:
        """
        Checks if a section exists in the configuration file.
        """
        return self.config.has_section(section)

    def get(self, section: str, key: str, fallback: str = None) -> str:
        """
        Retrieves a specific key, prioritizing overrides, then environment variables,
        then the config file.
        The lookup order is:
        1. Temporary override dictionary (for optimization)
        2. Bot-specific environment variable (e.g., MYBOT_MAX_TRADE_SIZE_USDT)
        3. Generic environment variable (e.g., MAX_TRADE_SIZE_USDT)
        4. Value from the .ini file (which can itself be an @env/ pointer)
        5. The provided fallback value.
        """
        env_key_name = key.upper()

        # 1. Check for temporary override
        if self.overrides and env_key_name in self.overrides:
            return self.overrides[env_key_name]

        # 2. Check for bot-specific environment variable (e.g., MY-BOT_MAX_TRADE_SIZE_USDT)
        if self.bot_name:
            bot_specific_env_key = f"{self.bot_name.upper().replace('-', '_')}_{env_key_name}"
            value = os.getenv(bot_specific_env_key)
            if value is not None:
                return value

        # 3. Check for generic environment variable
        value = os.getenv(env_key_name)
        if value is not None:
            return value

        # 4. If no direct env var, fall back to the existing .ini logic
        raw_value = self.config.get(section, key, fallback=None)

        if raw_value is None:
            # The key was not found in the .ini file at all.
            return fallback

        # The key exists in the .ini, now try to resolve its value (e.g., from an @env/ pointer).
        resolved_value = self._resolve_value(raw_value)

        if resolved_value is None:
            # The key was in the .ini but pointed to an env var that was not set.
            return fallback

        return resolved_value

    def getboolean(self, section: str, key: str, fallback: bool = None) -> bool:
        """
        Retrieves a specific key from a section as a boolean, resolving env vars.
        """
        value = self.get(section, key, fallback=None)

        if value is None:
            if fallback is not None:
                return fallback
            # This mimics configparser's behavior of raising an error if key not found and no fallback
            raise configparser.NoOptionError(key, section)

        # Evaluate the resolved value
        if isinstance(value, str):
            # Strip inline comments and whitespace
            cleaned_value = value.split('#')[0].strip()
            if cleaned_value.lower() in ('true', '1', 't', 'y', 'yes', 'on'):
                return True
            if cleaned_value.lower() in ('false', '0', 'f', 'n', 'no', 'off'):
                return False

        # If it's not a known string, it might be an invalid value.
        # Mimic configparser's error.
        raise ValueError(f'Not a boolean: {value}')

    def get_db_config(self, db_type: str) -> Dict[str, str]:
        """
        Constructs the database configuration from environment variables.
        This is the single source of truth for DB connection details.
        """
        if db_type.upper() == 'INFLUXDB':
            db_url = self._resolve_value("@env/INFLUXDB_URL")
            db_token = self._resolve_value("@env/INFLUXDB_TOKEN")
            db_org = self._resolve_value("@env/INFLUXDB_ORG")

            if not all([db_url, db_token, db_org]):
                raise ValueError(
                    "One or more required InfluxDB environment variables are missing: "
                    "INFLUXDB_URL, INFLUXDB_TOKEN, INFLUXDB_ORG"
                )

            return {
                "url": db_url,
                "token": db_token,
                "org": db_org
            }
        elif db_type.upper() == 'POSTGRES':
            return self.get_section('POSTGRES')
        else:
            raise ValueError(f"Invalid database type: {db_type}")


# Instantiate the config manager for global use
config_manager = ConfigManager()
