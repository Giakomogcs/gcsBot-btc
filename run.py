import os
import sys
import shutil
import typer
import subprocess
from typing import Optional
import glob
from jules_bot.utils import process_manager
try:
    import questionary
except ImportError:
    questionary = None

from jules_bot.database.postgres_manager import PostgresManager
from jules_bot.utils.config_manager import config_manager

PROJECT_NAME = "gcsbot-btc"
DOCKER_IMAGE_NAME = f"{PROJECT_NAME}-app"
DOCKER_NETWORK_NAME = f"{PROJECT_NAME}_default"
SUDO_PREFIX = ["sudo"] if os.name != "nt" else []

CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"]}
app = typer.Typer(context_settings=CONTEXT_SETTINGS)

@app.callback(invoke_without_command=True)
def main(ctx: typer.Context):
    if not os.path.exists(".env"):
        print("INFO: Arquivo '.env' não encontrado. Copiando de '.env.example'...")
        shutil.copy(".env.example", ".env")

def get_docker_compose_command():
    if shutil.which("docker-compose"):
        return SUDO_PREFIX + ["docker-compose"]
    elif shutil.which("docker"):
        try:
            subprocess.run(SUDO_PREFIX + ["docker", "compose", "--version"], capture_output=True, text=True, check=True)
            return SUDO_PREFIX + ["docker", "compose"]
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass
    raise FileNotFoundError("Could not find a valid 'docker-compose' or 'docker compose' command.")

def run_docker_compose_command(command_args: list, **kwargs):
    try:
        base_command = get_docker_compose_command()
        full_command = base_command + command_args
        print(f"   (usando comando: `{' '.join(full_command)}`)")
        kwargs.setdefault('capture_output', True)
        kwargs.setdefault('text', True)
        if kwargs.get('text'):
            kwargs['encoding'] = 'utf-8'
            kwargs['errors'] = 'ignore'
        result = subprocess.run(full_command, check=True, **kwargs)
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ Erro ao executar comando docker-compose (código de saída: {e.returncode}):")
        print(f"   --- STDOUT ---:\n{e.stdout}")
        print(f"   --- STDERR ---:\n{e.stderr}")
    except Exception as e:
        print(f"❌ Erro inesperado ao executar comando docker-compose: {e}")
    return False

def _ensure_env_is_running():
    try:
        base_command = get_docker_compose_command()
        check_command = base_command + ["ps", "-q", "postgres"]
        result = subprocess.run(check_command, capture_output=True, text=True, check=False)
        if not result.stdout.strip():
            print("🚀 Ambiente Docker não detectado. Iniciando serviços de suporte (PostgreSQL, etc.)...")
            
            print("   -> Etapa 1: Construindo a imagem da aplicação (isso pode levar um momento)...")
            # Run build with streaming output for better user feedback by setting capture_output=False
            if not run_docker_compose_command(["build"], capture_output=False):
                print("❌ Falha ao construir a imagem Docker. Verifique a sua instalação do Docker e o Dockerfile.")
                return False

            print("\n   -> Etapa 2: Iniciando os containers em background...")
            # Run 'up' without build, as it's already done
            if not run_docker_compose_command(["up", "-d"], capture_output=True):
                print("❌ Falha ao iniciar os containers Docker. Verifique a sua instalação do Docker.")
                return False
            
            print("✅ Serviços de ambiente iniciados com sucesso.")
    except Exception as e:
        print(f"❌ Erro inesperado ao verificar o ambiente Docker: {e}")
        return False
    return True

@app.command("start-env")
def start_env():
    if not _ensure_env_is_running():
        raise typer.Exit(1)
    print("✅ Ambiente Docker já está em execução ou foi iniciado com sucesso.")

@app.command("stop-env")
def stop_env():
    print("🛑 Parando todos os serviços Docker...")
    running_bots = process_manager.sync_and_get_running_bots()
    if running_bots:
        print("   Parando containers de bot em execução...")
        for bot in running_bots:
            try:
                subprocess.run(SUDO_PREFIX + ["docker", "stop", bot.container_id], capture_output=True, check=False)
                subprocess.run(SUDO_PREFIX + ["docker", "rm", bot.container_id], capture_output=True, check=False)
                process_manager.remove_running_bot(bot.bot_name)
            except Exception:
                pass
    if run_docker_compose_command(["down", "-v"], capture_output=True):
        print("✅ Ambiente Docker parado com sucesso.")

@app.command("status")
def status():
    print("📊 Verificando status dos serviços Docker...")
    run_docker_compose_command(["ps"])

def run_bot_in_container(bot_name: str, mode: str) -> Optional[str]:
    container_name = f"{PROJECT_NAME}-instance-{bot_name}-{mode}"
    try:
        print(f"   Verificando container existente '{container_name}'...")
        subprocess.run(SUDO_PREFIX + ["docker", "stop", container_name], capture_output=True, text=True, check=False)
        subprocess.run(SUDO_PREFIX + ["docker", "rm", container_name], capture_output=True, text=True, check=False)
    except Exception:
        pass
    command = SUDO_PREFIX + ["docker", "run", "--detach", "--name", container_name, "--network", DOCKER_NETWORK_NAME, "--env-file", ".env", "-e", f"BOT_NAME={bot_name}", "-e", f"BOT_MODE={mode}", "-e", "JULES_BOT_SCRIPT_MODE=1", DOCKER_IMAGE_NAME, "python", "jules_bot/main.py"]
    print(f"   (executando: `{' '.join(command)}`)")
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=True)
        container_id = result.stdout.strip()
        if not container_id:
            print("❌ Falha ao obter o ID do container do comando 'docker run'.")
            print(f"   Stderr: {result.stderr}")
            return None
        return container_id
    except FileNotFoundError:
        print("❌ Erro: O comando 'docker' não foi encontrado. O Docker está instalado e no seu PATH?")
        return None
    except subprocess.CalledProcessError as e:
        print(f"❌ Erro ao executar 'docker run'. Código de saída: {e.returncode}")
        print(f"   Stderr:\n{e.stderr}")
        print(f"   Stdout:\n{e.stdout}")
        return None
    return None

def run_command_in_container(command: list, bot_name: str, interactive: bool = False):
    run_command = SUDO_PREFIX + ["docker", "run", "--rm", "--network", DOCKER_NETWORK_NAME, "--env-file", ".env", "-e", f"BOT_NAME={bot_name}", "-e", "JULES_BOT_SCRIPT_MODE=1"]
    if interactive:
        run_command.append("-it")
    run_command.extend([DOCKER_IMAGE_NAME, "python"])
    run_command.extend(command)
    print(f"   (executando: `{' '.join(run_command)}`)")
    try:
        subprocess.run(run_command, check=True)
        return True
    except Exception as e:
        print(f"❌ Falha ao executar comando no container: {e}")
        return False

def _confirm_and_clear_data(bot_name: str):
    if typer.confirm(f"⚠️ ATENÇÃO: Deseja limpar TODOS os dados do banco de dados para o bot '{bot_name}' antes de continuar?"):
        print(f"🗑️ Limpando dados para o bot '{bot_name}'...")
        if not run_command_in_container(["scripts/wipe_database.py", "--force"], bot_name):
            print("❌ Falha ao limpar os dados. Abortando.")
            raise typer.Exit(code=1)
        print("✅ Dados limpos com sucesso.")
    else:
        print("👍 Ok, os dados não foram alterados.")

def _setup_bot_run(bot_name: Optional[str]) -> str:
    if bot_name:
        available_bots = _get_bots_from_env()
        if bot_name not in available_bots:
            print(f"❌ Bot '{bot_name}' não encontrado. Bots disponíveis: {', '.join(available_bots)}")
            raise typer.Exit(1)
        return bot_name
    return _interactive_bot_selection()

@app.command()
def trade(bot_name: Optional[str] = typer.Option(None, "--bot-name", "-n", help="O nome do bot para executar."), detached: Optional[bool] = typer.Option(None, "--detached", "-d", help="Executa em segundo plano. Se não for especificado, será perguntado.")):
    if not _ensure_env_is_running():
        raise typer.Exit(1)
    was_interactive = bot_name is None
    final_bot_name = _setup_bot_run(bot_name)
    mode = "trade"
    final_detached = detached
    if was_interactive and final_detached is None:
        final_detached = questionary.confirm("Executar este bot em modo detached (segundo plano)?").ask()
        if final_detached is None: raise typer.Exit()
    if not final_detached or not process_manager.get_bot_by_name(final_bot_name):
        _confirm_and_clear_data(final_bot_name)
    if final_detached:
        print(f"🚀 Iniciando o bot '{final_bot_name}' em modo '{mode.upper()}' em SEGUNDO PLANO...")
        container_id = run_bot_in_container(final_bot_name, mode)
        if container_id:
            process_manager.add_running_bot(final_bot_name, container_id, mode)
            print(f"✅ Bot '{final_bot_name}' iniciado com sucesso. ID do Container: {container_id[:12]}")
            print(f"   Para ver os logs, use: python run.py logs --bot-name {final_bot_name}")
        else:
            print(f"❌ Falha ao iniciar o bot '{final_bot_name}'.")
    else:
        print("Executar em primeiro plano não é mais suportado na nova arquitetura. Use o modo detached.")
        raise typer.Exit(1)

@app.command()
def test(bot_name: Optional[str] = typer.Option(None, "--bot-name", "-n", help="O nome do bot para executar."), detached: Optional[bool] = typer.Option(None, "--detached", "-d", help="Executa em segundo plano. Se não for especificado, será perguntado.")):
    if not _ensure_env_is_running():
        raise typer.Exit(1)
    was_interactive = bot_name is None
    final_bot_name = _setup_bot_run(bot_name)
    mode = "test"
    final_detached = detached
    if was_interactive and final_detached is None:
        final_detached = questionary.confirm("Executar este bot em modo detached (segundo plano)?").ask()
        if final_detached is None: raise typer.Exit()
    if not final_detached or not process_manager.get_bot_by_name(final_bot_name):
        _confirm_and_clear_data(final_bot_name)
    if final_detached:
        print(f"🚀 Iniciando o bot '{final_bot_name}' em modo '{mode.upper()}' em SEGUNDO PLANO...")
        container_id = run_bot_in_container(final_bot_name, mode)
        if container_id:
            process_manager.add_running_bot(final_bot_name, container_id, mode)
            print(f"✅ Bot '{final_bot_name}' iniciado com sucesso. ID do Container: {container_id[:12]}")
            print(f"   Para ver os logs, use: python run.py logs --bot-name {final_bot_name}")
        else:
            print(f"❌ Falha ao iniciar o bot '{final_bot_name}'.")
    else:
        print("Executar em primeiro plano não é mais suportado na nova arquitetura. Use o modo detached.")
        raise typer.Exit(1)

@app.command("list-bots")
def list_bots():
    print("🤖 Verificando bots em execução...")
    running_bots = process_manager.sync_and_get_running_bots()
    if not running_bots:
        print("ℹ️ Nenhum bot em execução no momento.")
        return
    from tabulate import tabulate
    headers = ["Bot Name", "Mode", "Container ID", "Status", "Start Time"]
    table_data = [[b.bot_name, b.bot_mode, b.container_id[:12], "Running", b.start_time] for b in running_bots]
    print(tabulate(table_data, headers=headers, tablefmt="heavy_grid"))

@app.command("stop-bot")
def stop_bot(bot_name: Optional[str] = typer.Option(None, "--bot-name", "-n", help="Nome do bot para parar.")):
    running_bots = process_manager.sync_and_get_running_bots()
    if not running_bots:
        print("ℹ️ Nenhum bot em execução para parar.")
        raise typer.Exit()
    bot_to_stop = None
    if bot_name:
        bot_to_stop = next((b for b in running_bots if b.bot_name == bot_name), None)
        if not bot_to_stop:
            print(f"❌ Bot '{bot_name}' não está em execução.")
            raise typer.Exit(1)
    else:
        bot_choices = [b.bot_name for b in running_bots]
        selected_name = questionary.select("Selecione o bot para parar:", choices=sorted(bot_choices)).ask()
        if not selected_name: raise typer.Exit()
        bot_to_stop = next((b for b in running_bots if b.bot_name == selected_name), None)
    if not bot_to_stop:
        print("❌ Seleção inválida.")
        raise typer.Exit(1)
    print(f"🛑 Parando e removendo o container do bot '{bot_to_stop.bot_name}'...")
    try:
        subprocess.run(SUDO_PREFIX + ["docker", "stop", bot_to_stop.container_id], check=True, capture_output=True)
        subprocess.run(SUDO_PREFIX + ["docker", "rm", bot_to_stop.container_id], check=True, capture_output=True)
        process_manager.remove_running_bot(bot_to_stop.bot_name)
        print(f"✅ Bot '{bot_to_stop.bot_name}' parado com sucesso.")
    except subprocess.CalledProcessError as e:
        if "No such container" in e.stderr:
            print(f"⚠️ Container para o bot '{bot_to_stop.bot_name}' já não existia. Removendo da lista.")
            process_manager.remove_running_bot(bot_to_stop.bot_name)
        else:
            print(f"❌ Erro ao parar o container: {e.stderr}")

@app.command("logs")
def logs(bot_name: Optional[str] = typer.Option(None, "--bot-name", "-n", help="Nome do bot para ver os logs.")):
    running_bots = process_manager.sync_and_get_running_bots()
    if not running_bots:
        print("ℹ️ Nenhum bot em execução para ver os logs.")
        raise typer.Exit()
    bot_to_log = None
    if bot_name:
        bot_to_log = next((b for b in running_bots if b.bot_name == bot_name), None)
        if not bot_to_log:
            print(f"❌ Bot '{bot_name}' não está em execução.")
            raise typer.Exit(1)
    else:
        bot_choices = [b.bot_name for b in running_bots]
        selected_name = questionary.select("Selecione o bot para ver os logs:", choices=sorted(bot_choices)).ask()
        if not selected_name: raise typer.Exit()
        bot_to_log = next((b for b in running_bots if b.bot_name == selected_name), None)
    if not bot_to_log:
        print("❌ Seleção inválida.")
        raise typer.Exit(1)
    print(f"📄 Acompanhando logs do bot '{bot_to_log.bot_name}' (Container: {bot_to_log.container_id[:12]})...")
    print("   (Pressione Ctrl+C para parar)")
    try:
        subprocess.run(SUDO_PREFIX + ["docker", "logs", "-f", bot_to_log.container_id])
    except KeyboardInterrupt:
        print("\n🛑 Acompanhamento de logs interrompido.")
    except Exception as e:
        print(f"❌ Erro ao obter logs: {e}")

@app.command("display")
def display(bot_name: Optional[str] = typer.Option(None, "--bot-name", "-n", help="Nome do bot para visualizar.")):
    running_bots = process_manager.sync_and_get_running_bots()
    if not running_bots:
        print("ℹ️ Nenhum bot em execução para monitorar.")
        raise typer.Exit()
    bot_to_display = None
    if bot_name:
        bot_to_display = next((b for b in running_bots if b.bot_name == bot_name), None)
        if not bot_to_display:
            print(f"❌ Bot '{bot_name}' não está em execução.")
            raise typer.Exit(1)
    else:
        bot_choices = [b.bot_name for b in running_bots]
        selected_name = questionary.select("Selecione o bot para monitorar:", choices=sorted(bot_choices)).ask()
        if not selected_name: raise typer.Exit()
        bot_to_display = next((b for b in running_bots if b.bot_name == selected_name), None)
    if not bot_to_display:
        print("❌ Seleção inválida.")
        raise typer.Exit(1)
    print(f"🚀 Iniciando o display para o bot '{bot_to_display.bot_name}'...")
    try:
        tui_env = os.environ.copy()
        tui_env["BOT_NAME"] = bot_to_display.bot_name
        tui_env["DOCKER_NETWORK_NAME"] = DOCKER_NETWORK_NAME
        tui_env["PROJECT_NAME"] = PROJECT_NAME
        command = [sys.executable, "tui/app.py", "--mode", bot_to_display.bot_mode, "--container-id", bot_to_display.container_id]
        print(f"   (executando: `{' '.join(command)}`)")
        subprocess.run(command, env=tui_env, check=True)
    except Exception as e:
        print(f"❌ Erro ao iniciar o display: {e}")
    print("\n✅ Display encerrado.")

import re

def _get_bots_from_env(env_file_path: str = ".env") -> list[str]:
    if not os.path.exists(env_file_path): return ["jules_bot"]
    bots = {"jules_bot"}
    with open(env_file_path, "r", encoding='utf-8') as f:
        for line in f:
            match = re.match(r'^([A-Z0-9_-]+?)_BINANCE_(?:TESTNET_)?API_KEY=', line.strip())
            if match:
                bots.add(match.group(1).lower())
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
    print("🤖 Criando um novo bot...")
    env_file = ".env"
    if questionary is None:
        print("❌ A biblioteca 'questionary' não está instalada. Por favor, instale com 'pip install questionary'.")
        raise typer.Exit(1)
    if not os.path.exists(env_file) and os.path.exists(".env.example"):
        print(f"INFO: Arquivo '{env_file}' não encontrado. Copiando de '.env.example'...")
        shutil.copy(".env.example", env_file)
    bot_name = questionary.text("Qual o nome do novo bot? (use apenas letras minúsculas, números, '_' e '-', sem espaços)", validate=lambda text: True if re.match(r"^[a-z0-9_-]+$", text) else "Nome inválido. Use apenas letras minúsculas, números, '_' e '-', sem espaços.").ask()
    if not bot_name:
        print("👋 Operação cancelada.")
        raise typer.Exit()
    available_bots = _get_bots_from_env(env_file)
    if bot_name in available_bots:
        print(f"❌ O bot '{bot_name}' já existe no arquivo {env_file}.")
        raise typer.Exit(1)
    prefix = bot_name.upper()
    bot_config_block = NEW_BOT_TEMPLATE.format(bot_name=bot_name, prefix=prefix)
    try:
        with open(env_file, "a", encoding='utf-8') as f:
            f.write(f"\n{bot_config_block}")
        print(f"✅ Bot '{bot_name}' adicionado com sucesso ao seu arquivo {env_file}!")
        print(f"   -> Agora, edite o arquivo e preencha com as chaves de API do bot.")
    except Exception as e:
        print(f"❌ Ocorreu um erro ao escrever no arquivo {env_file}: {e}")
        raise typer.Exit(1)

@app.command("delete-bot")
def delete_bot():
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
    bot_to_delete = questionary.select("Selecione o bot que deseja deletar:", choices=sorted(deletable_bots)).ask()
    if not bot_to_delete:
        print("👋 Operação cancelada.")
        raise typer.Exit()
    confirmed = questionary.confirm(f"Você tem certeza que deseja deletar o bot '{bot_to_delete}'? Isso removerá todas as suas variáveis de configuração (com prefixo '{bot_to_delete.upper()}_') do arquivo {env_file}.").ask()
    if not confirmed:
        print("👋 Operação cancelada.")
        raise typer.Exit()
    try:
        with open(env_file, "r", encoding='utf-8') as f:
            lines = f.readlines()
        prefix_to_delete = f"{bot_to_delete.upper()}_"
        lines_to_keep = [line for line in lines if not line.strip().startswith(prefix_to_delete)]
        with open(env_file, "w", encoding='utf-8') as f:
            f.writelines(lines_to_keep)
        print(f"✅ Bot '{bot_to_delete}' deletado com sucesso do arquivo {env_file}!")
    except Exception as e:
        print(f"❌ Ocorreu um erro ao processar o arquivo {env_file}: {e}")
        raise typer.Exit(1)

def _interactive_bot_selection() -> str:
    available_bots = _get_bots_from_env()
    if not available_bots:
        print("❌ Nenhum bot encontrado. Use o comando 'new-bot' para criar um.")
        raise typer.Exit(1)
    if questionary is None:
        print("❌ A biblioteca 'questionary' é necessária para o modo interativo.")
        raise typer.Exit(1)
    if len(available_bots) == 1:
        selected_bot_name = available_bots[0]
        print(f"✅ Bot '{selected_bot_name}' selecionado automaticamente.")
        return selected_bot_name
    selected_bot_name = questionary.select("Selecione o bot:", choices=sorted(available_bots)).ask()
    if selected_bot_name is None:
        print("👋 Operação cancelada.")
        raise typer.Exit()
    return selected_bot_name

@app.command()
def validate(bot_name: Optional[str] = typer.Option(None, "--bot-name", "-n", help="O nome do bot para validar.")):
    """Executa o script de validação de dados no container."""
    if not _ensure_env_is_running():
        raise typer.Exit(1)
    
    final_bot_name = _setup_bot_run(bot_name)
    print(f"🔎 Executando script de validação de dados para o bot '{final_bot_name}'...")
    if not run_command_in_container(["scripts/validate_trade_data.py", final_bot_name], final_bot_name):
        print("❌ Falha ao executar o script de validação.")
    else:
        print("✅ Script de validação concluído.")


@app.command()
def backtest(bot_name: Optional[str] = typer.Option(None, "--bot-name", "-n", help="O nome do bot para executar."), days: int = typer.Option(30, "--days", "-d", help="Número de dias de dados recentes para o backtest.")):
    final_bot_name = _setup_bot_run(bot_name)
    print(f"🚀 Iniciando execução de backtest para {days} dias para o bot '{final_bot_name}'...")
    print("\n--- Etapa 1 de 2: Preparando dados ---")
    if not run_command_in_container(["scripts/prepare_backtest_data.py", str(days)], final_bot_name):
        print("❌ Falha na preparação dos dados. Abortando backtest.")
        return
    print("\n--- Etapa 2 de 2: Rodando o backtest ---")
    if not run_command_in_container(["scripts/run_backtest.py", str(days)], final_bot_name):
        print("❌ Falha na execução do backtest.")
        return
    print("\n✅ Backtest finalizado com sucesso.")

if __name__ == "__main__":
    app()
