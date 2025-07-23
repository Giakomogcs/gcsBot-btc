import os
from dynaconf import Dynaconf

# Obtenha o caminho absoluto para o diretório do projeto
# (assumindo que o config.py está em src/ e settings.toml está na raiz)
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

settings = Dynaconf(
    envvar_prefix="DYNACONF",
    settings_files=[
        os.path.join(project_root, 'settings.toml'),
        os.path.join(project_root, '.secrets.toml')
    ],
    environments=True,
    load_dotenv=True,
    env_switcher="ENV_FOR_DYNACONF",
    default_env="default",
)

# `envvar_prefix` = export envvars with `export DYNACONF_FOO=bar`.
# `settings_files` = Load these files in order.
