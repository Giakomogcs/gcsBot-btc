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

# State dictionary to hold the bot name
state = {
    "bot_name": "jules_bot",
}

@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    bot_name: str = typer.Option(
        "jules_bot",
        "--bot-name",
        "-n",
        help="O nome do bot para isolamento de logs e dados. Padrão: 'jules_bot'"
    )
):
    """
    Jules Bot - A crypto trading bot.
    """
    # Garante que o arquivo .env exista, se não, cria a partir do .env.dummy
    if not os.path.exists(".env") and os.path.exists(".env.dummy"):
        print("INFO: Arquivo '.env' não encontrado. Copiando de '.env.dummy'...")
        shutil.copy(".env.dummy", ".env")

    # We only set the bot name if a subcommand is invoked
    # that is not an environment-level command.
    env_commands = ["start", "stop", "status", "logs", "build", "new-bot", "delete-bot"]
    if ctx.invoked_subcommand and ctx.invoked_subcommand not in env_commands:
        state["bot_name"] = bot_name

    # ENV_FILE is no longer needed, as docker-compose will use the root .env by default

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

@app.command("run-tests")
def run_tests(
    pytest_args: str = typer.Option(
        "",
        "--pytest-args",
        "-a",
        help="Argumentos adicionais para passar ao pytest, entre aspas."
    )
):
    """Executa a suíte de testes (pytest) dentro do container."""
    print(" запускаем тесты...")
    command = ["-m", "pytest"]
    if pytest_args:
        # Naively split by space. For complex args, consider shlex.
        command.extend(pytest_args.split())

    _run_in_container(command=command)

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


def _setup_bot_run(bot_name: Optional[str]) -> str:
    """
    Determines the bot to run, either from the command line option or an interactive menu.
    Updates the global state with the chosen bot name.
    """
    final_bot_name = bot_name
    if final_bot_name is None:
        final_bot_name = _interactive_bot_selection()
    else:
        available_bots = _get_bots_from_env()
        if final_bot_name not in available_bots:
            print(f"❌ Bot '{final_bot_name}' não encontrado. Bots disponíveis: {', '.join(available_bots)}")
            raise typer.Exit(1)

    # Update state for other functions to use
    state["bot_name"] = final_bot_name
    return final_bot_name

@app.command()
def trade(
    bot_name: Optional[str] = typer.Option(None, "--bot-name", "-n", help="O nome do bot para executar. Se não for fornecido, um menu será exibido.")
):
    """Inicia o bot em modo de negociação (live)."""
    final_bot_name = _setup_bot_run(bot_name)
    mode = "trade"
    _confirm_and_clear_data(mode)
    print(f"🚀 Iniciando o bot '{final_bot_name}' em modo '{mode.upper()}'...")
    _run_in_container(
        command=["jules_bot/main.py"],
        env_vars={"BOT_MODE": mode}
    )

@app.command()
def test(
    bot_name: Optional[str] = typer.Option(None, "--bot-name", "-n", help="O nome do bot para executar. Se não for fornecido, um menu será exibido.")
):
    """Inicia o bot em modo de teste (testnet), opcionalmente limpando o estado anterior."""
    final_bot_name = _setup_bot_run(bot_name)
    mode = "test"
    _confirm_and_clear_data(mode)
    print(f"🚀 Iniciando o bot '{final_bot_name}' em modo '{mode.upper()}'...")
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


import re

def _get_bots_from_env(env_file_path: str = ".env") -> list[str]:
    """
    Scans the .env file for bot-specific variables and returns a list of unique bot names.
    It looks for variables starting with a prefix like 'BOTNAME_'
    """
    if not os.path.exists(env_file_path):
        return ["jules_bot"] # Default bot if no .env file

    bots = set()
    # The default bot 'jules_bot' is always available, as it can use non-prefixed vars.
    bots.add("jules_bot")

    with open(env_file_path, "r", encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue

            # Match lines like BOTNAME_BINANCE_API_KEY= or BOTNAME_BINANCE_TESTNET_API_KEY=
            # This is a good indicator of a bot's config block.
            # Updated regex to include hyphens to find existing bots with names like 'gcs-bot'
            match = re.match(r'^([A-Z0-9_-]+?)_BINANCE_(?:TESTNET_)?API_KEY=', line)
            if match:
                bot_name_upper = match.group(1)
                bots.add(bot_name_upper.lower())

    return sorted(list(bots))


NEW_BOT_TEMPLATE = """
# ==============================================================================
# BOT: {bot_name}
# ==============================================================================
{prefix}_BINANCE_API_KEY=SUA_API_KEY_REAL
{prefix}_BINANCE_API_SECRET=SEU_API_SECRET_REAL
{prefix}_BINANCE_TESTNET_API_KEY=SUA_CHAVE_DE_API_TESTNET
{prefix}_BINANCE_TESTNET_API_SECRET=SEU_SEGREDO_DE_API_TESTNET

# Você pode também sobrescrever outras variáveis para este bot, por exemplo:
# {prefix}_APP_SYMBOL=ETHUSDT
# {prefix}_STRATEGY_RULES_TARGET_PROFIT=0.0040
# ==============================================================================
"""

@app.command("new-bot")
def new_bot():
    """
    Adiciona a configuração para um novo bot no arquivo .env principal.
    """
    print("🤖 Criando um novo bot...")
    env_file = ".env"

    if questionary is None:
        print("❌ A biblioteca 'questionary' não está instalada. Por favor, instale com 'pip install questionary'.")
        raise typer.Exit(1)

    # Garante que o .env exista, se não, cria a partir do .env.dummy
    if not os.path.exists(env_file) and os.path.exists(".env.dummy"):
        print(f"INFO: Arquivo '{env_file}' não encontrado. Copiando de '.env.dummy'...")
        shutil.copy(".env.dummy", env_file)

    # Pergunta o nome do bot
    bot_name = questionary.text(
        "Qual o nome do novo bot? (use apenas letras minúsculas, números, '_' e '-', sem espaços)",
        validate=lambda text: True if re.match(r"^[a-z0-9_-]+$", text) else "Nome inválido. Use apenas letras minúsculas, números, '_' e '-', sem espaços."
    ).ask()

    if not bot_name:
        print("👋 Operação cancelada.")
        raise typer.Exit()

    # Verifica se o bot já existe
    available_bots = _get_bots_from_env(env_file)
    if bot_name in available_bots:
        print(f"❌ O bot '{bot_name}' já existe no arquivo {env_file}.")
        raise typer.Exit(1)

    # Adiciona o novo bloco de configuração ao arquivo .env
    prefix = bot_name.upper()
    bot_config_block = NEW_BOT_TEMPLATE.format(bot_name=bot_name, prefix=prefix)

    try:
        with open(env_file, "a", encoding='utf-8') as f:
            f.write(bot_config_block)
        print(f"✅ Bot '{bot_name}' adicionado com sucesso ao seu arquivo {env_file}!")
        print(f"   -> Agora, edite o arquivo e preencha com as chaves de API do bot.")
    except Exception as e:
        print(f"❌ Ocorreu um erro ao escrever no arquivo {env_file}: {e}")
        raise typer.Exit(1)


@app.command("delete-bot")
def delete_bot():
    """
    Remove a configuração de um bot do arquivo .env principal.
    """
    print("🗑️  Deletando um bot...")
    env_file = ".env"

    if questionary is None:
        print("❌ A biblioteca 'questionary' não está instalada. Por favor, instale com 'pip install questionary'.")
        raise typer.Exit(1)

    if not os.path.exists(env_file):
        print(f"❌ Arquivo de ambiente '{env_file}' não encontrado. Nada para deletar.")
        raise typer.Exit(1)

    available_bots = _get_bots_from_env(env_file)
    deletable_bots = [bot for bot in available_bots if bot != "jules_bot"]

    if not deletable_bots:
        print("ℹ️ Nenhum bot personalizável para deletar. O bot padrão 'jules_bot' não pode ser deletado.")
        raise typer.Exit()

    bot_to_delete = questionary.select(
        "Selecione o bot que deseja deletar:",
        choices=sorted(deletable_bots)
    ).ask()

    if not bot_to_delete:
        print("👋 Operação cancelada.")
        raise typer.Exit()

    confirmed = questionary.confirm(
        f"Você tem certeza que deseja deletar o bot '{bot_to_delete}'? Isso removerá todas as suas variáveis de configuração (com prefixo '{bot_to_delete.upper()}_') do arquivo {env_file}."
    ).ask()

    if not confirmed:
        print("👋 Operação cancelada.")
        raise typer.Exit()

    try:
        with open(env_file, "r", encoding='utf-8') as f:
            content = f.read()

        # Regex para encontrar o bloco de comentário do bot
        bot_block_regex = re.compile(
            r'\n*# =+[\r\n]+'
            r'# BOT: ' + re.escape(bot_to_delete) + r'[\r\n]+'
            r'# =+[\r\n]+'
            r'(.+?[\r\n]+)+'
            r'# =+[\r\n]+',
            re.DOTALL
        )

        # Remove o bloco de comentário
        new_content = bot_block_regex.sub('', content)

        # Remove linhas que começam com o prefixo do bot
        prefix_to_delete = f"{bot_to_delete.upper()}_"
        lines = new_content.splitlines(True)
        lines_to_keep = [line for line in lines if not line.strip().startswith(prefix_to_delete)]

        with open(env_file, "w", encoding='utf-8') as f:
            f.writelines(lines_to_keep)

        print(f"✅ Bot '{bot_to_delete}' deletado com sucesso do arquivo {env_file}!")
    except Exception as e:
        print(f"❌ Ocorreu um erro ao processar o arquivo {env_file}: {e}")
        raise typer.Exit(1)


def _interactive_bot_selection() -> str:
    """
    Displays an interactive menu for the user to select a bot.
    Returns the selected bot's name.
    Handles errors and user cancellation gracefully.
    """
    available_bots = _get_bots_from_env()
    if not available_bots:
        print("❌ Nenhum bot encontrado. Use o comando 'new-bot' para criar um.")
        raise typer.Exit(1)

    if questionary is None:
        print("❌ A biblioteca 'questionary' não está instalada. Por favor, instale com 'pip install questionary' para usar o modo interativo.")
        print(f"   Como alternativa, especifique um bot com --bot-name. Bots disponíveis: {', '.join(available_bots)}")
        raise typer.Exit(1)

    if len(available_bots) == 1:
        selected_bot_name = available_bots[0]
        print(f"✅ Bot '{selected_bot_name}' selecionado automaticamente (único disponível).")
    else:
        selected_bot_name = questionary.select(
            "Selecione o bot:",
            choices=sorted(available_bots)
        ).ask()

        if selected_bot_name is None:
            print("👋 Operação cancelada.")
            raise typer.Exit()

    return selected_bot_name


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
    final_bot_name = _setup_bot_run(bot_name)

    print(f"🚀 Iniciando o display para o bot '{final_bot_name}' no modo '{mode.upper()}'...")
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
