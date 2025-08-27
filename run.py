import os
import sys
import shutil
import typer
import subprocess
from typing import Optional
import glob
try:
    import questionary
except ImportError:
    questionary = None

from jules_bot.database.postgres_manager import PostgresManager
from jules_bot.utils.config_manager import config_manager

CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"]}
app = typer.Typer(context_settings=CONTEXT_SETTINGS)

# State dictionary to hold the bot name and env file
state = {
    "bot_name": "jules_bot",
    "env_file": "env/default.env"
}

@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    bot_name: str = typer.Option("jules_bot", "--bot-name", "-n", help="O nome do bot para isolamento de logs e dados."),
    env_file: str = typer.Option("env/default.env", "--env-file", "-e", help="Caminho para o arquivo .env a ser usado.")
):
    """
    Jules Bot - A crypto trading bot.
    """
    # --- Auto-configuração do ambiente ---
    env_dir = "env"
    example_file_path = os.path.join(env_dir, "example.env")

    # Garante que o diretório 'env' exista
    if not os.path.exists(env_dir):
        print(f"INFO: Diretório '{env_dir}' não encontrado. Criando...")
        os.makedirs(env_dir)

    # Garante que o arquivo de exemplo exista para o comando 'new-bot'
    if not os.path.exists(example_file_path):
        print(f"INFO: Arquivo de template '{example_file_path}' não encontrado. Criando um template completo...")
        template_content = '''# .env.example - Template para configuração do Bot

# --- Segredos da API ---
# Substitua pelos seus valores reais. Use as chaves de TESTNET se BOT_MODE='test'
BINANCE_API_KEY=SUA_API_KEY_REAL
BINANCE_API_SECRET=SEU_API_SECRET_REAL
BINANCE_TESTNET_API_KEY=SUA_CHAVE_DE_API_TESTNET
BINANCE_TESTNET_API_SECRET=SEU_SEGREDO_DE_API_TESTNET

# --- Configurações do Bot ---
# Define o modo de operação do bot. Obrigatório.
# Opções: 'trade' (real), 'test' (testnet)
BOT_MODE=test

# --- Configuração do Banco de Dados ---
# Usado pelo bot para se conectar ao container do Postgres
POSTGRES_HOST=postgres
POSTGRES_USER=gcs_user
POSTGRES_PASSWORD=gcs_password
POSTGRES_DB=gcs_db
POSTGRES_PORT=5432

# --- Configurações da Estratégia (Strategy Rules) ---
STRATEGY_RULES_COMMISSION_RATE=0.001
STRATEGY_RULES_SELL_FACTOR=1
STRATEGY_RULES_TARGET_PROFIT=0.0035
STRATEGY_RULES_MAX_CAPITAL_PER_TRADE_PERCENT=0.15
STRATEGY_RULES_BASE_USD_PER_TRADE=10
STRATEGY_RULES_MAX_OPEN_POSITIONS=150
STRATEGY_RULES_USE_DYNAMIC_CAPITAL=true
STRATEGY_RULES_WORKING_CAPITAL_PERCENTAGE=0.85
STRATEGY_RULES_USE_PERCENTAGE_BASED_SIZING=true
STRATEGY_RULES_ORDER_SIZE_FREE_CASH_PERCENTAGE=0.004
STRATEGY_RULES_USE_FORMULA_SIZING=true
STRATEGY_RULES_MIN_ORDER_PERCENTAGE=0.004
STRATEGY_RULES_MAX_ORDER_PERCENTAGE=0.02
STRATEGY_RULES_LOG_SCALING_FACTOR=0.002
STRATEGY_RULES_USE_REVERSAL_BUY_STRATEGY=true
STRATEGY_RULES_REVERSAL_BUY_THRESHOLD_PERCENT=0.005
STRATEGY_RULES_REVERSAL_MONITORING_TIMEOUT_SECONDS=100

# --- Configurações de Backtest ---
BACKTEST_INITIAL_BALANCE=100
BACKTEST_COMMISSION_FEE=0.1
BACKTEST_DEFAULT_LOOKBACK_DAYS=10

# --- Configurações da Aplicação ---
APP_SYMBOL=BTCUSDT
APP_FORCE_OFFLINE_MODE=false
APP_USE_TESTNET=true
APP_EQUITY_RECALCULATION_INTERVAL=300

# --- Configurações da API (para o servidor de dados) ---
API_PORT=8765
API_MEASUREMENT=price_data
API_UPDATE_INTERVAL=5
'''
        with open(example_file_path, "w", encoding='utf-8') as f:
            f.write(template_content)

    # We only set the bot name and env file if a subcommand is invoked
    # that is not an environment-level command.
    env_commands = ["start", "stop", "status", "logs", "build"]
    if ctx.invoked_subcommand and ctx.invoked_subcommand not in env_commands:
        state["bot_name"] = bot_name
        state["env_file"] = env_file
        os.environ["ENV_FILE"] = env_file # Set ENV_FILE for docker-compose
    # For env_commands, ENV_FILE is not set, so docker-compose uses its own safe default.

# --- Lógica de Detecção do Docker Compose ---

def get_docker_compose_command():
    """
    Verifica se 'docker-compose' (V1) ou 'docker compose' (V2) está disponível.
    """
    # Tenta encontrar um comando docker-compose válido
    if shutil.which("docker-compose"):
        return ["docker-compose"]
    elif shutil.which("docker"):
        try:
            # Constrói o comando de teste completo (ex: ['docker', 'compose', '--version'])
            test_command = ["docker", "compose", "--version"]
            result = subprocess.run(test_command, capture_output=True, text=True, check=True)
            if "Docker Compose version" in result.stdout:
                return ["docker", "compose"]
        except (subprocess.CalledProcessError, FileNotFoundError):
            # Se o teste falhar, continuamos para o erro final
            pass
    
    # Se nenhuma versão do comando foi encontrada
    raise FileNotFoundError("Could not find a valid 'docker-compose' or 'docker compose' command. Please ensure Docker is installed and in your PATH.")

def run_docker_command(command_args: list, **kwargs):
    """
    Helper para executar comandos docker e lidar com erros de forma robusta.
    Garante a decodificação de output em UTF-8.
    """
    try:
        base_command = get_docker_compose_command()
        full_command = base_command + command_args
        print(f"   (usando comando: `{' '.join(full_command)}`)")

        # Se o output for capturado, garante que seja decodificado como texto UTF-8.
        # Isso evita a necessidade de `.decode()` no bloco de exceção e previne erros de encoding.
        if kwargs.get("capture_output"):
            kwargs.setdefault("text", True)
            kwargs.setdefault("encoding", "utf-8")
            kwargs.setdefault("errors", "replace")

        # Para comandos de ambiente, não precisamos de output em tempo real, então 'run' é ok.
        subprocess.run(full_command, check=True, **kwargs)
        return True
    except FileNotFoundError as e:
        print(f"❌ Erro: {e}")
    except subprocess.CalledProcessError as e:
        print(f"❌ Erro ao executar comando. Código de saída: {e.returncode}")
        # Com text=True, stdout/stderr já são strings, não bytes.
        if e.stderr:
            print(f"   Stderr:\n{e.stderr}")
        if e.stdout:
            print(f"   Stdout:\n{e.stdout}")
    except Exception as e:
        print(f"❌ Ocorreu um erro inesperado: {e}")
    return False


# --- Comandos do Ambiente Docker ---

@app.command("start")
def start():
    """Constrói e inicia todos os serviços em modo detached."""
    print("🚀 Iniciando serviços Docker...")
    if run_docker_command(["up", "-d"], capture_output=True):
        print("✅ Serviços iniciados com sucesso.")
        print("   O container 'app' está rodando em modo idle.")
        print("   Use `python run.py trade`, `test`, ou `backtest` para executar tarefas.")

@app.command("stop")
def stop():
    """Para e remove todos os serviços."""
    print("🛑 Parando serviços Docker...")
    if run_docker_command(["down", "-v"], capture_output=True):
        print("✅ Serviços parados com sucesso.")

@app.command("status")
def status():
    """Mostra o status de todos os serviços."""
    print("📊 Verificando status dos serviços Docker...")
    run_docker_command(["ps"])

@app.command("logs")
def logs(service_name: Optional[str] = typer.Argument(None, help="Nome do serviço para ver os logs (ex: 'app', 'db').")):
    """Acompanha os logs de um serviço específico ou de todos."""
    try:
        base_command = get_docker_compose_command()
        full_command = base_command + ["logs", "-f"]

        if service_name:
            print(f"📄 Acompanhando logs do serviço '{service_name}'...")
            full_command.append(service_name)
        else:
            print("📄 Acompanhando logs de todos os serviços...")

        print(f"   (Pressione Ctrl+C para parar)")
        subprocess.run(full_command)

    except KeyboardInterrupt:
        print("\n🛑 Acompanhamento de logs interrompido.")
    except Exception as e:
        print(f"❌ Erro ao obter logs: {e}")

@app.command("build")
def build():
    """Força a reconstrução das imagens Docker sem iniciá-las."""
    print("🛠️ Forçando reconstrução das imagens Docker...")
    if run_docker_command(["build", "--no-cache"]):
        print("✅ Imagens reconstruídas com sucesso.")

# --- Comandos da Aplicação ---

def _run_in_container(command: list, env_vars: dict = {}, interactive: bool = False, detached: bool = False):
    """
    Executa um comando Python dentro do container 'app'.
    - Modo Padrão (interactive=False): Captura e exibe o output em tempo real.
    - Modo Interativo (interactive=True): Anexa o terminal ao processo (para TUIs).
    - Modo Detached (detached=True): Executa o comando em segundo plano.
    """
    try:
        docker_cmd = get_docker_compose_command()

        exec_cmd = docker_cmd + ["exec"]
        if detached:
            exec_cmd.append("-d")
        elif interactive:
            exec_cmd.append("-it")

        # Add bot_name to env_vars
        env_vars["BOT_NAME"] = state["bot_name"]

        for key, value in env_vars.items():
            exec_cmd.extend(["-e", f"{key}={value}"])

        # Comando final a ser executado no container
        container_command = ["app", "python"] + command
        exec_cmd.extend(container_command)

        print(f"   (executando: `{' '.join(exec_cmd)}`)")

        if interactive:
            # Para TUIs e outros aplicativos interativos, precisamos que o processo
            # anexe diretamente ao terminal do host.
            # `subprocess.run` sem capturar I/O (stdout, stderr, stdin) é a forma
            # correta de ceder o controle do terminal ao processo filho.
            # NOTA PARA WINDOWS: Para que a TUI funcione corretamente, é altamente
            # recomendável usar um terminal moderno como o Windows Terminal. O CMD
            # e o PowerShell legados podem ter problemas com a renderização.
            result = subprocess.run(exec_cmd, check=False)
            if result.returncode != 0:
                print(f"\n❌ Comando interativo finalizado com código de saída: {result.returncode}")
            return result.returncode == 0
        else:
            # Para logs, usamos Popen para streaming de output em tempo real
            process = subprocess.Popen(exec_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, encoding='utf-8', errors='replace')

            # Lê e imprime cada linha de output assim que ela aparece
            for line in iter(process.stdout.readline, ''):
                print(line, end='')

            process.wait()
            process.stdout.close()

            if process.returncode != 0:
                print(f"\n❌ Comando falhou com código de saída: {process.returncode}")
                return False
            return True

    except Exception as e:
        print(f"❌ Ocorreu um erro ao executar o comando no container: {e}")
        import traceback
        traceback.print_exc()
        return False


def _confirm_and_clear_data(mode: str):
    """
    Asks the user for confirmation to clear data for a specific mode.
    If confirmed, runs the appropriate data clearing script.
    """
    prompt_message = f"Você deseja limpar todos os dados existentes do modo '{mode}' para o bot '{state['bot_name']}' antes de continuar?"
    if mode == 'trade':
        prompt_message = f"⚠️ ATENÇÃO: Você está em modo 'trade' (live). Deseja limpar TODOS os dados do banco de dados (trades, status, histórico) para o bot '{state['bot_name']}' antes de continuar?"

    if typer.confirm(prompt_message):
        print(f"🗑️  Limpando dados do modo '{mode}' para o bot '{state['bot_name']}'...")
        script_command = []
        if mode == 'test':
            script_command = ["scripts/clear_testnet_trades.py"]
        elif mode == 'trade':
            # Using wipe_database with --force because confirmation was already given.
            script_command = ["scripts/wipe_database.py", "--force"]
        elif mode == 'backtest':
            script_command = ["scripts/clear_trades_measurement.py", "backtest"]

        if not _run_in_container(command=script_command):
            print(f"❌ Falha ao limpar os dados do modo '{mode}'. Abortando.")
            raise typer.Exit(code=1)
        print(f"✅ Dados do modo '{mode}' limpos com sucesso.")
    else:
        print(f"👍 Ok, os dados do modo '{mode}' não foram alterados.")


@app.command()
def trade(
    bot_name: Optional[str] = typer.Option(None, "--bot-name", "-n", help="O nome do bot para executar. Se não for fornecido, um menu será exibido.")
):
    """Inicia o bot em modo de negociação (live)."""
    final_bot_name = bot_name

    if final_bot_name is None:
        final_bot_name, final_env_file = _interactive_bot_selection()
    else:
        available_bots = _get_available_bots()
        if final_bot_name not in available_bots:
            print(f"❌ Bot '{final_bot_name}' não encontrado. Bots disponíveis: {', '.join(available_bots.keys())}")
            raise typer.Exit(1)
        final_env_file = available_bots[final_bot_name]

    # Update state for other functions to use
    state["bot_name"] = final_bot_name
    state["env_file"] = final_env_file
    os.environ["ENV_FILE"] = final_env_file

    mode = "trade"
    _confirm_and_clear_data(mode)
    print(f"🚀 Iniciando o bot '{state['bot_name']}' em modo '{mode.upper()}'...")
    _run_in_container(
        command=["jules_bot/main.py"],
        env_vars={"BOT_MODE": mode}
    )

@app.command()
def test(
    bot_name: Optional[str] = typer.Option(None, "--bot-name", "-n", help="O nome do bot para executar. Se não for fornecido, um menu será exibido.")
):
    """Inicia o bot em modo de teste (testnet), opcionalmente limpando o estado anterior."""
    final_bot_name = bot_name

    if final_bot_name is None:
        final_bot_name, final_env_file = _interactive_bot_selection()
    else:
        available_bots = _get_available_bots()
        if final_bot_name not in available_bots:
            print(f"❌ Bot '{final_bot_name}' não encontrado. Bots disponíveis: {', '.join(available_bots.keys())}")
            raise typer.Exit(1)
        final_env_file = available_bots[final_bot_name]

    # Update state for other functions to use
    state["bot_name"] = final_bot_name
    state["env_file"] = final_env_file
    os.environ["ENV_FILE"] = final_env_file

    mode = "test"
    _confirm_and_clear_data(mode)
    print(f"🚀 Iniciando o bot '{state['bot_name']}' em modo '{mode.upper()}'...")
    _run_in_container(
        command=["jules_bot/main.py"],
        env_vars={"BOT_MODE": mode}
    )

@app.command()
def backtest(
    days: int = typer.Option(
        30, "--days", "-d", help="Número de dias de dados recentes para o backtest."
    )
):
    """Prepara os dados e executa um backtest completo dentro do container."""
    mode = "backtest"
    _confirm_and_clear_data(mode)

    print(f"🚀 Iniciando execução de backtest para {days} dias para o bot '{state['bot_name']}'...")

    print("\n--- Etapa 1 de 2: Preparando dados ---")
    if not _run_in_container(["scripts/prepare_backtest_data.py", str(days)]):
        print("❌ Falha na preparação dos dados. Abortando backtest.")
        return

    print("\n--- Etapa 2 de 2: Rodando o backtest ---")
    if not _run_in_container(["scripts/run_backtest.py", str(days)]):
        print("❌ Falha na execução do backtest.")
        return

    print("\n✅ Backtest finalizado com sucesso.")


def _get_available_bots() -> dict[str, str]:
    """
    Scans the 'env/' directory for .env files and returns a dictionary of
    bot_name: file_path.
    """
    bots = {}
    env_dir = "env"
    # Scan for all files ending with .env in the env/ directory
    for env_file in glob.glob(os.path.join(env_dir, "*.env")):
        filename = os.path.basename(env_file)
        # The bot name is the filename without the .env extension
        bot_name = filename[:-4]

        if bot_name == "default":
            # The default.env file corresponds to the main 'jules_bot'
            bots["jules_bot"] = env_file
        elif bot_name == "example":
            # Ignore the example file
            continue
        else:
            bots[bot_name] = env_file
    return bots


@app.command("new-bot")
def new_bot():
    """
    Creates a new .env file for a new bot from the env/example.env template.
    """
    print("🤖 Criando um novo bot...")

    if questionary is None:
        print("❌ A biblioteca 'questionary' não está instalada. Por favor, instale com 'pip install questionary'.")
        raise typer.Exit(1)

    # Check for template file
    template_file = "env/example.env"
    if not os.path.exists(template_file):
        print(f"❌ Arquivo de template '{template_file}' não encontrado. Não é possível criar um novo bot.")
        raise typer.Exit(1)

    # Ask for bot name
    bot_name = questionary.text(
        "Qual o nome do novo bot? (letras minúsculas, sem espaços)",
        validate=lambda text: True if text and ' ' not in text and text.islower() else "Nome inválido. Use apenas letras minúsculas e sem espaços."
    ).ask()

    if not bot_name:
        print("👋 Operação cancelada.")
        raise typer.Exit()

    # Create new env file name
    new_env_file = f"env/{bot_name}.env"

    # Check if file already exists
    if os.path.exists(new_env_file):
        print(f"❌ O arquivo de ambiente '{new_env_file}' para o bot '{bot_name}' já existe.")
        raise typer.Exit(1)

    # Copy the template
    try:
        shutil.copy(template_file, new_env_file)
        print(f"✅ Bot '{bot_name}' criado com sucesso!")
        print(f"   -> O arquivo de configuração '{new_env_file}' foi criado.")
        print(f"   -> Agora, edite este arquivo e preencha com suas chaves de API e outras configurações.")
    except Exception as e:
        print(f"❌ Ocorreu um erro ao criar o arquivo: {e}")
        raise typer.Exit(1)


@app.command("delete-bot")
def delete_bot():
    """
    Deletes a bot's .env file after interactive selection and confirmation.
    """
    print("🗑️  Deletando um bot...")

    if questionary is None:
        print("❌ A biblioteca 'questionary' não está instalada. Por favor, instale com 'pip install questionary'.")
        raise typer.Exit(1)

    available_bots = _get_available_bots()

    # Exclude the default bot from deletion for safety
    deletable_bots = {name: path for name, path in available_bots.items() if name != "jules_bot"}

    if not deletable_bots:
        print("ℹ️ Nenhum bot personalizável para deletar. O bot padrão 'jules_bot' não pode ser deletado.")
        raise typer.Exit()

    # Select bot to delete
    bot_to_delete = questionary.select(
        "Selecione o bot que deseja deletar:",
        choices=sorted(list(deletable_bots.keys()))
    ).ask()

    if not bot_to_delete:
        print("👋 Operação cancelada.")
        raise typer.Exit()

    env_file_to_delete = deletable_bots[bot_to_delete]

    # Confirmation
    confirmed = questionary.confirm(
        f"Você tem certeza que deseja deletar o bot '{bot_to_delete}'? Isso removerá o arquivo '{env_file_to_delete}' permanentemente."
    ).ask()

    if not confirmed:
        print("👋 Operação cancelada.")
        raise typer.Exit()

    # Delete the file
    try:
        os.remove(env_file_to_delete)
        print(f"✅ Bot '{bot_to_delete}' deletado com sucesso!")
        print(f"   -> O arquivo de configuração '{env_file_to_delete}' foi removido.")
    except OSError as e:
        print(f"❌ Ocorreu um erro ao deletar o arquivo: {e}")
        raise typer.Exit(1)


def _interactive_bot_selection() -> tuple[str, str]:
    """
    Displays an interactive menu for the user to select a bot.
    Returns the selected bot's name and its .env file path.
    Handles errors and user cancellation gracefully.
    """
    available_bots = _get_available_bots()
    if not available_bots:
        print("❌ Nenhum bot encontrado. Crie um arquivo de configuração em 'env/' com a extensão .env (ex: env/meu-bot.env).")
        raise typer.Exit(1)

    if questionary is None:
        print("❌ A biblioteca 'questionary' não está instalada. Por favor, instale com 'pip install questionary' para usar o modo interativo.")
        print(f"   Como alternativa, especifique um bot com --bot-name. Bots disponíveis: {', '.join(available_bots.keys())}")
        raise typer.Exit(1)

    if len(available_bots) == 1:
        selected_bot_name = list(available_bots.keys())[0]
        print(f"✅ Bot '{selected_bot_name}' selecionado automaticamente (único disponível).")
    else:
        selected_bot_name = questionary.select(
            "Selecione o bot:",
            choices=sorted(list(available_bots.keys()))
        ).ask()

        if selected_bot_name is None:
            print("👋 Operação cancelada.")
            raise typer.Exit()

    selected_env_file = available_bots[selected_bot_name]
    return selected_bot_name, selected_env_file


@app.command("display")
def display(
    bot_name: Optional[str] = typer.Option(
        None,
        "--bot-name",
        "-n",
        help="O nome do bot para visualizar. Se não for fornecido, um menu de seleção será exibido."
    ),
    mode: str = typer.Option(
        "test", "--mode", "-m", help="O modo de operação a ser monitorado ('trade' ou 'test')."
    )
):
    """Inicia o display (TUI) para monitoramento e controle."""
    final_bot_name = bot_name

    if final_bot_name is None:
        # User did not specify a bot, so we start the interactive selection.
        final_bot_name, final_env_file = _interactive_bot_selection()
    else:
        # User specified a bot, so we find its env file.
        available_bots = _get_available_bots()
        if final_bot_name not in available_bots:
            print(f"❌ Bot '{final_bot_name}' não encontrado. Bots disponíveis: {', '.join(available_bots.keys())}")
            raise typer.Exit(1)
        final_env_file = available_bots[final_bot_name]

    # Update the global state and environment variables for the container
    state["bot_name"] = final_bot_name
    state["env_file"] = final_env_file
    os.environ["ENV_FILE"] = final_env_file

    print(f"🚀 Iniciando o display para o bot '{state['bot_name']}' no modo '{mode.upper()}'...")
    print("   Lembre-se que o bot (usando 'trade' ou 'test') deve estar rodando em outro terminal.")

    command_to_run = ["tui/app.py", "--mode", mode]

    _run_in_container(
        command=command_to_run,
        interactive=True
    )
    print("\n✅ Display encerrado.")


@app.command("clear-backtest-trades")
def clear_backtest_trades():
    """Deletes all trades from the 'backtest' environment in the database."""
    print(f"🗑️  Attempting to clear all backtest trades from the database for bot '{state['bot_name']}'...")
    _run_in_container(
        command=["scripts/clear_trades_measurement.py", "backtest"],
        interactive=True
    )

@app.command("clear-testnet-trades")
def clear_testnet_trades():
    """Deletes all trades from the 'test' environment in the database."""
    print(f"🗑️  Attempting to clear all testnet trades from the database for bot '{state['bot_name']}'...")
    _run_in_container(
        command=["scripts/clear_testnet_trades.py"],
        interactive=True
    )


@app.command("wipe-db")
def wipe_db():
    """
    Shows a confirmation prompt and then wipes all data from the main tables.
    This is a destructive operation.
    """
    print(f"🗑️  Attempting to wipe the database for bot '{state['bot_name']}'...")
    print("   This will run the script inside the container.")

    _run_in_container(
        command=["scripts/wipe_database.py"],
        interactive=True
    )


if __name__ == "__main__":
    app()
