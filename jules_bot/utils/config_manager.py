import configparser
from pathlib import Path
from typing import Dict

class ConfigManager:
    """
    A class to manage loading and accessing configuration from a .ini file.
    """
    def __init__(self, config_file: Path = Path('config.ini')):
        """
        Initializes the ConfigManager and loads the configuration file.
        Args:
            config_file: The path to the configuration file.
        """
        self.config = configparser.ConfigParser()
        if not config_file.exists():
            raise FileNotFoundError(f"Configuration file not found: {config_file}")
        self.config.read(config_file)

    def get_section(self, section: str) -> Dict[str, str]:
        """
        Retrieves a section from the configuration as a dictionary.
        Args:
            section: The name of the section to retrieve.
        Returns:
            A dictionary containing the key-value pairs of the section.
        """
        if self.config.has_section(section):
            return dict(self.config.items(section))
        return {}

    def get(self, section: str, key: str, fallback: str = None) -> str:
        """
        Retrieves a specific key from a section.
        """
        return self.config.get(section, key, fallback=fallback)

    def getboolean(self, section: str, key: str, fallback: bool = None) -> bool:
        """
        Retrieves a specific key from a section as a boolean.
        """
        return self.config.getboolean(section, key, fallback=fallback)

# Instantiate the config manager for global use
config_manager = ConfigManager()
