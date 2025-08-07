from jules_bot.utils.config_manager import settings

class GCSBotConfig:
    def __init__(self):
        self.config = settings.model_dump()

    def get(self, key, default=None):
        return self.config.get(key, default)
