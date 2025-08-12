import configparser
import os
from pathlib import Path
from typing import Dict, Optional
from dotenv import load_dotenv

class ConfigManager:
    """
    A class to manage loading and accessing configuration from a .ini file.
    It can resolve values from environment variables using the @env/ syntax.
    """
    def __init__(self, config_file: Path = Path('config.ini')):
        """
        Initializes the ConfigManager and loads the configuration file.
        Args:
            config_file: The path to the configuration file.
        """
        load_dotenv()
        self.config = configparser.ConfigParser()
        if not config_file.exists():
            raise FileNotFoundError(f"Configuration file not found: {config_file}")
        self.config.read(config_file)

    def _resolve_value(self, value: str) -> Optional[str]:
        """
        Resolves a value from an environment variable if it starts with @env/.
        """
        if isinstance(value, str) and value.startswith('@env/'):
            env_var_name = value[5:]
            return os.getenv(env_var_name)
        return value

    def get_section(self, section: str) -> Dict[str, str]:
        """
        Retrieves a section from the configuration as a dictionary, resolving env vars.
        """
        if self.config.has_section(section):
            section_items = self.config.items(section)
            return {key: self._resolve_value(value) for key, value in section_items}
        return {}

    def get(self, section: str, key: str, fallback: str = None) -> str:
        """
        Retrieves a specific key from a section, resolving env vars.
        """
        # Get the raw value from configparser
        value = self.config.get(section, key, fallback=fallback)

        # If the retrieved value is the fallback, don't try to resolve it, just return it.
        # This can happen if the key does not exist in the .ini file.
        if value == fallback:
            return fallback

        return self._resolve_value(value)

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
            if value.lower() in ('true', '1', 't', 'y', 'yes', 'on'):
                return True
            if value.lower() in ('false', '0', 'f', 'n', 'no', 'off'):
                return False

        # If it's not a known string, it might be an invalid value.
        # Mimic configparser's error.
        raise ValueError(f'Not a boolean: {value}')

    def get_db_config(self) -> Dict[str, str]:
        """
        Constructs the database configuration from environment variables.
        This is the single source of truth for DB connection details.
        """
        db_url = os.getenv("INFLUXDB_URL")
        db_token = os.getenv("INFLUXDB_APP_TOKEN")
        db_org = os.getenv("INFLUXDB_ORG")

        if not all([db_url, db_token, db_org]):
            raise ValueError(
                "One or more required InfluxDB environment variables are missing: "
                "INFLUXDB_URL, INFLUXDB_APP_TOKEN, INFLUXDB_ORG"
            )

        return {
            "url": db_url,
            "token": db_token,
            "org": db_org
        }


# Instantiate the config manager for global use
config_manager = ConfigManager()
