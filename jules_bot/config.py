from jules_bot.utils.config_manager import config_manager

class GCSBotConfig:
    def __init__(self):
        self.config = {}
        for section in config_manager.config.sections():
            self.config[section.lower()] = config_manager.get_section(section)

    def get(self, key, default=None):
        key_parts = key.split('.')
        if len(key_parts) == 2:
            section, option = key_parts
            return self.config.get(section, {}).get(option, default)

        for section in self.config.values():
            if key in section:
                return section[key]
        return default
