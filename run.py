import os
import sys
import shutil
import typer
import subprocess
import time
import traceback
from typing import Optional, List
import glob
import json
from pathlib import Path
from jules_bot.utils import process_manager
try:
    import questionary
except ImportError:
    questionary = None
try:
    import optuna
except ImportError:
    optuna = None

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

import socket
import errno

def find_free_port(start_port=8766, exclude_ports=None):
    if exclude_ports is None:
        exclude_ports = []
    port = start_port
    while port <= 65535:
        if port in exclude_ports:
            port += 1
            continue
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('0.0.0.0', port))
                return port
        except OSError as e:
            if e.errno == errno.EADDRINUSE or (hasattr(e, 'winerror') and e.winerror == 10048):
                port += 1
            else:
                raise
    raise IOError("Could not find a free port.")

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

def _check_image_exists() -> bool:
    try:
        cmd = SUDO_PREFIX + ["docker", "image", "inspect", DOCKER_IMAGE_NAME]
        subprocess.run(cmd, check=True, capture_output=True)
        return True
    except subprocess.CalledProcessError:
        return False
    except Exception:
        return False

def _build_app_image(force: bool = False) -> bool:
    if not force and _check_image_exists():
        print(f"✅ Imagem Docker '{DOCKER_IMAGE_NAME}' já existe. Pulando a construção.")
        return True

    print(f"\n{'🔧 Forçando a reconstrução' if force else '🔨 Construindo'} da imagem da aplicação (isso pode levar um momento)...")
    build_command = SUDO_PREFIX + ["docker", "build", "-t", DOCKER_IMAGE_NAME, "."]
    if force:
        build_command.append("--no-cache")
    print(f"   (usando comando: `{' '.join(build_command)}`)")
    try:
        subprocess.run(build_command, check=True)
        print(f"✅ Imagem '{DOCKER_IMAGE_NAME}' construída com sucesso.")
    except subprocess.CalledProcessError:
        print(f"❌ Falha ao construir a imagem Docker. Verifique o output acima.")
        return False
    except Exception as e:
        print(f"❌ Erro inesperado ao construir a imagem Docker: {e}")
        return False

    print("\n   -> Limpando imagens antigas (dangling)...")
    prune_command = SUDO_PREFIX + ["docker", "image", "prune", "-f"]
    try:
        subprocess.run(prune_command, check=True, capture_output=True, text=True)
        print("✅ Limpeza de imagens antigas concluída.")
    except Exception as e:
        print(f"⚠️  Não foi possível limpar as imagens antigas: {e}")

    return True

def _ensure_env_is_running(rebuild: bool = False):
    if rebuild or not _check_image_exists():
        if not _build_app_image(force=rebuild):
            return False
    try:
        base_command = get_docker_compose_command()
        check_command = base_command + ["ps", "-q", "postgres"]
        result = subprocess.run(check_command, capture_output=True, text=True, check=False)

        if not result.stdout.strip():
            print("🚀 Ambiente Docker de serviços não detectado. Iniciando (PostgreSQL, etc.)...")
            if not run_docker_compose_command(["up", "-d", "postgres", "pgadmin"], capture_output=False):
                print("❌ Falha ao iniciar os containers de serviço. Verifique a sua instalação do Docker.")
                return False
            print("✅ Serviços de ambiente iniciados com sucesso.")
        else:
            print("✅ Serviços Docker (PostgreSQL, etc.) já estão em execução.")
    except Exception as e:
        print(f"❌ Erro inesperado ao verificar ou iniciar o ambiente Docker: {e}")
        return False
    return True

@app.command("start-env")
def start_env(rebuild: bool = typer.Option(False, "--rebuild", help="Força a reconstrução da imagem da aplicação.")):
    if not _ensure_env_is_running(rebuild=rebuild):
        raise typer.Exit(1)
    print("✅ Ambiente Docker pronto para uso.")

@app.command("rebuild-app")
def rebuild_app():
    print("Forçando a reconstrução da imagem da aplicação...")
    if not _build_app_image(force=True):
        print("❌ A reconstrução falhou. Verifique os logs acima.")
        raise typer.Exit(1)
    print("✅ Imagem da aplicação reconstruída com sucesso.")

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
    if run_docker_compose_command(["down", "--volumes"], capture_output=True):
        print("✅ Ambiente Docker (serviços) parado com sucesso.")
    else:
        print("⚠️  Houve um problema ao parar o ambiente de serviços com docker-compose.")
    print(f"ℹ️  A imagem da aplicação '{DOCKER_IMAGE_NAME}' foi mantida. Use 'python run.py rebuild-app' para reconstruí-la.")

@app.command("status")
def status():
    print("📊 Verificando status dos serviços Docker...")
    run_docker_compose_command(["ps"])

def run_bot_in_container(bot_name: str, mode: str) -> tuple[Optional[str], int]:
    container_name = f"{PROJECT_NAME}-instance-{bot_name}-{mode}"
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '.'))
    try:
        print(f"   Verificando container existente '{container_name}'...")
        subprocess.run(SUDO_PREFIX + ["docker", "stop", container_name], capture_output=True, text=True, check=False)
        subprocess.run(SUDO_PREFIX + ["docker", "rm", container_name], capture_output=True, text=True, check=False)
    except Exception:
        pass
    
    tui_files_dir = os.path.join(project_root, ".tui_files")
    os.makedirs(tui_files_dir, mode=0o777, exist_ok=True)

    try:
        running_bots = process_manager.sync_and_get_running_bots()
        used_ports = [bot.host_port for bot in running_bots]
        host_port = find_free_port(exclude_ports=used_ports)
        print(f"   API do bot será exposta na porta do host: {host_port}")
    except IOError as e:
        print(f"❌ Erro: {e}")
        return None, -1

    command = SUDO_PREFIX + ["docker", "run", "--detach", "--name", container_name, "--network", DOCKER_NETWORK_NAME, "--env-file", ".env", "-e", f"BOT_NAME={bot_name}", "-e", f"BOT_MODE={mode}", "-e", "JULES_BOT_SCRIPT_MODE=1", "-e", f"API_PORT={host_port}", "-p", f"{host_port}:{host_port}", "-v", f"{project_root}:/app", "-v", f"{tui_files_dir}:/app/.tui_files", DOCKER_IMAGE_NAME, "python", "jules_bot/main.py"]
    
    print(f"   (executando: `{' '.join(command)}`)")
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=True)
        container_id = result.stdout.strip()
        if not container_id:
            print("❌ Falha ao obter o ID do container do comando 'docker run'.")
            print(f"   Stderr: {result.stderr}")
            return None, -1
        return container_id, host_port
    except FileNotFoundError:
        print("❌ Erro: O comando 'docker' não foi encontrado. O Docker está instalado e no seu PATH?")
        return None, -1
    except subprocess.CalledProcessError as e:
        print(f"❌ Erro ao executar 'docker run'. Código de saída: {e.returncode}")
        print(f"   Stderr:\n{e.stderr}")
        print(f"   Stdout:\n{e.stdout}")
        return None, -1
    except Exception:
        print("❌ Erro inesperado durante a execução do container.")
        traceback.print_exc()
        return None, -1

def run_script_in_background_container(process_name: str, context_bot_name: str, command: list) -> Optional[str]:
    """
    Runs a given command in a new, detached Docker container and returns the container ID.
    The container is named based on the process_name for easy identification and tracking.
    The BOT_NAME environment variable is set to context_bot_name to ensure the script
    runs with the correct data and configuration context.
    """
    container_name = f"{PROJECT_NAME}-instance-{process_name}"
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '.'))

    # Clean up any old container with the same name
    try:
        subprocess.run(SUDO_PREFIX + ["docker", "stop", container_name], capture_output=True, text=True, check=False)
        subprocess.run(SUDO_PREFIX + ["docker", "rm", container_name], capture_output=True, text=True, check=False)
    except Exception:
        pass  # Ignore errors if the container doesn't exist

    # Garante que o diretório .tui_files exista no host
    tui_files_dir = os.path.join(project_root, ".tui_files")
    os.makedirs(tui_files_dir, mode=0o777, exist_ok=True)

    docker_command = SUDO_PREFIX + [
        "docker", "run", "--detach",
        "--name", container_name,
        "--network", DOCKER_NETWORK_NAME,
        "--env-file", ".env",
        "-e", f"BOT_NAME={context_bot_name}",  # Use the context name for the env var
        "-e", "JULES_BOT_SCRIPT_MODE=1",
        "-v", f"{project_root}:/app",
        "-v", f"{tui_files_dir}:/app/.tui_files",  # Monta o diretório .tui_files
        DOCKER_IMAGE_NAME,
        "python"
    ] + command
    
    print(f"   (executando em background: `{' '.join(docker_command)}`)")
    try:
        result = subprocess.run(docker_command, capture_output=True, text=True, check=True)
        container_id = result.stdout.strip()
        if not container_id:
            print("❌ Falha ao obter o ID do container do comando 'docker run'.")
            print(f"   Stderr: {result.stderr}")
            return None
        return container_id
    except subprocess.CalledProcessError as e:
        print(f"❌ Erro ao executar o container em background. Código de saída: {e.returncode}")
        print(f"   Stderr:\n{e.stderr}")
        return None
    except Exception as e:
        print(f"❌ Erro inesperado durante a execução do container: {e}")
        traceback.print_exc()
        return None

def run_command_in_container(command: list, bot_name: str, interactive: bool = False, extra_env_files: Optional[List[str]] = None, non_blocking: bool = False, suppress_output: bool = False):
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '.'))
    
    run_command = SUDO_PREFIX + [
        "docker", "run", "--rm",
        "--network", DOCKER_NETWORK_NAME,
    ]

    env_files = [".env"]
    if extra_env_files:
        env_files.extend(extra_env_files)

    for env_file in env_files:
        if os.path.exists(env_file):
            run_command.extend(["--env-file", env_file])
        else:
            print(f"⚠️  Aviso: Arquivo de ambiente '{env_file}' não encontrado e será ignorado.")

    run_command.extend([
        "-v", f"{project_root}:/app",
        "-e", f"BOT_NAME={bot_name}",
        "-e", "JULES_BOT_SCRIPT_MODE=1"
    ])
    
    if interactive:
        run_command.append("-it")
        
    run_command.extend([DOCKER_IMAGE_NAME, "python"])
    run_command.extend(command)
    
    if not suppress_output:
        print(f"   (executando: `{' '.join(run_command)}`)")

    popen_kwargs = {}
    if suppress_output:
        popen_kwargs['stdout'] = subprocess.DEVNULL
        popen_kwargs['stderr'] = subprocess.DEVNULL

    if non_blocking:
        return subprocess.Popen(run_command, **popen_kwargs)

    try:
        subprocess.run(run_command, check=True, **popen_kwargs)
        return True
    except subprocess.CalledProcessError as e:
        if not suppress_output:
            print(f"❌ Falha ao executar comando no container. Código de saída: {e.returncode}")
        return False
    except Exception as e:
        if not suppress_output:
            print(f"❌ Falha inesperada ao executar comando no container: {e}")
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

    # Check if an optimizer for this bot is already running.
    optimizer_process_name = f"{final_bot_name}-optimizer"
    existing_optimizer = process_manager.get_bot_by_name(optimizer_process_name)
    if existing_optimizer:
        print(f"❌ Erro: Uma otimização para o bot '{final_bot_name}' já está em execução.")
        print("   Você não pode iniciar o bot em modo TRADE enquanto a otimização está ativa.")
        print(f"   Para parar a otimização, use: python run.py stop-bot --name {optimizer_process_name}")
        raise typer.Exit(1)

    mode = "trade"
    final_detached = detached
    if was_interactive and final_detached is None:
        final_detached = questionary.confirm("Executar este bot em modo detached (segundo plano)?").ask()
        if final_detached is None: raise typer.Exit()
    if not final_detached or not process_manager.get_bot_by_name(final_bot_name):
        _confirm_and_clear_data(final_bot_name)
    if final_detached:
        print(f"🚀 Iniciando o bot '{final_bot_name}' em modo '{mode.upper()}' em SEGUNDO PLANO...")
        container_id, host_port = run_bot_in_container(final_bot_name, mode)
        if container_id and host_port > 0:
            process_manager.add_running_bot(final_bot_name, container_id, mode, host_port)
            print(f"✅ Bot '{final_bot_name}' iniciado com sucesso. ID do Container: {container_id[:12]}")
            print(f"   API está acessível em: http://localhost:{host_port}")
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

    # Check if an optimizer for this bot is already running.
    optimizer_process_name = f"{final_bot_name}-optimizer"
    existing_optimizer = process_manager.get_bot_by_name(optimizer_process_name)
    if existing_optimizer:
        print(f"❌ Erro: Uma otimização para o bot '{final_bot_name}' já está em execução.")
        print("   Você não pode iniciar o bot em modo TEST enquanto a otimização está ativa.")
        print(f"   Para parar a otimização, use: python run.py stop-bot --name {optimizer_process_name}")
        raise typer.Exit(1)

    mode = "test"
    final_detached = detached
    if was_interactive and final_detached is None:
        final_detached = questionary.confirm("Executar este bot em modo detached (segundo plano)?").ask()
        if final_detached is None: raise typer.Exit()
    if not final_detached or not process_manager.get_bot_by_name(final_bot_name):
        _confirm_and_clear_data(final_bot_name)
    if final_detached:
        print(f"🚀 Iniciando o bot '{final_bot_name}' em modo '{mode.upper()}' em SEGUNDO PLANO...")
        container_id, host_port = run_bot_in_container(final_bot_name, mode)
        if container_id and host_port > 0:
            process_manager.add_running_bot(final_bot_name, container_id, mode, host_port)
            print(f"✅ Bot '{final_bot_name}' iniciado com sucesso. ID do Container: {container_id[:12]}")
            print(f"   API está acessível em: http://localhost:{host_port}")
            print(f"   Para ver os logs, use: python run.py logs --bot-name {final_bot_name}")
        else:
            print(f"❌ Falha ao iniciar o bot '{final_bot_name}'.")
    else:
        print("Executar em primeiro plano não é mais suportado na nova arquitetura. Use o modo detached.")
        raise typer.Exit(1)

@app.command("list-bots")
def list_bots():
    print("🤖 Verificando processos em execução...")
    running_processes = process_manager.sync_and_get_running_bots()
    if not running_processes:
        print("ℹ️ Nenhum processo em execução no momento.")
        return
    from tabulate import tabulate
    headers = ["Process Name", "Type", "Mode", "Container ID", "Status", "Start Time"]
    table_data = [[
        b.bot_name,
        b.process_type.upper(),
        b.bot_mode,
        b.container_id[:12],
        "Running",
        b.start_time
    ] for b in running_processes]
    print(tabulate(table_data, headers=headers, tablefmt="heavy_grid"))

@app.command("stop-bot")
def stop_bot(process_name: Optional[str] = typer.Option(None, "--name", "-n", help="Nome do processo para parar.")):
    running_processes = process_manager.sync_and_get_running_bots()
    if not running_processes:
        print("ℹ️ Nenhum processo em execução para parar.")
        raise typer.Exit()
    process_to_stop = None
    if process_name:
        process_to_stop = next((p for p in running_processes if p.bot_name == process_name), None)
        if not process_to_stop:
            print(f"❌ Processo '{process_name}' não está em execução.")
            raise typer.Exit(1)
    else:
        choices = [p.bot_name for p in running_processes]
        selected_name = questionary.select("Selecione o processo para parar:", choices=sorted(choices)).ask()
        if not selected_name: raise typer.Exit()
        process_to_stop = next((p for p in running_processes if p.bot_name == selected_name), None)
    if not process_to_stop:
        print("❌ Seleção inválida.")
        raise typer.Exit(1)
    print(f"🛑 Parando e removendo o container do processo '{process_to_stop.bot_name}'...")
    try:
        subprocess.run(SUDO_PREFIX + ["docker", "stop", process_to_stop.container_id], check=True, capture_output=True)
        subprocess.run(SUDO_PREFIX + ["docker", "rm", process_to_stop.container_id], check=True, capture_output=True)
        process_manager.remove_running_bot(process_to_stop.bot_name)
        print(f"✅ Processo '{process_to_stop.bot_name}' parado com sucesso.")
    except subprocess.CalledProcessError as e:
        if "No such container" in e.stderr:
            print(f"⚠️ Container para o processo '{process_to_stop.bot_name}' já não existia. Removendo da lista.")
            process_manager.remove_running_bot(process_to_stop.bot_name)
        else:
            print(f"❌ Erro ao parar o container: {e.stderr}")

@app.command("logs")
def logs(process_name: Optional[str] = typer.Option(None, "--name", "-n", help="Nome do processo para ver os logs.")):
    running_processes = process_manager.sync_and_get_running_bots()
    if not running_processes:
        print("ℹ️ Nenhum processo em execução para ver os logs.")
        raise typer.Exit()
    process_to_log = None
    if process_name:
        process_to_log = next((p for p in running_processes if p.bot_name == process_name), None)
        if not process_to_log:
            print(f"❌ Processo '{process_name}' não está em execução.")
            raise typer.Exit(1)
    else:
        choices = [p.bot_name for p in running_processes]
        selected_name = questionary.select("Selecione o processo para ver os logs:", choices=sorted(choices)).ask()
        if not selected_name: raise typer.Exit()
        process_to_log = next((p for p in running_processes if p.bot_name == selected_name), None)
    if not process_to_log:
        print("❌ Seleção inválida.")
        raise typer.Exit(1)
    print(f"📄 Acompanhando logs do processo '{process_to_log.bot_name}' (Container: {process_to_log.container_id[:12]})...")
    print("   (Pressione Ctrl+C para parar)")
    try:
        subprocess.run(SUDO_PREFIX + ["docker", "logs", "-f", process_to_log.container_id])
    except KeyboardInterrupt:
        print("\n🛑 Acompanhamento de logs interrompido.")
    except Exception as e:
        print(f"❌ Erro ao obter logs: {e}")

@app.command("display")
def display(process_name: Optional[str] = typer.Option(None, "--name", "-n", help="Nome do processo para visualizar.")):
    running_processes = process_manager.sync_and_get_running_bots()
    if not running_processes:
        print("ℹ️ Nenhum processo em execução para monitorar.")
        raise typer.Exit()
    
    process_to_display = None
    if process_name:
        process_to_display = next((p for p in running_processes if p.bot_name == process_name), None)
        if not process_to_display:
            print(f"❌ Processo '{process_name}' não está em execução.")
            raise typer.Exit(1)
    else:
        choices = [p.bot_name for p in running_processes]
        selected_name = questionary.select("Selecione o processo para monitorar:", choices=sorted(choices)).ask()
        if not selected_name: raise typer.Exit()
        process_to_display = next((p for p in running_processes if p.bot_name == selected_name), None)

    if not process_to_display:
        print("❌ Seleção inválida.")
        raise typer.Exit(1)

    print(f"🚀 Iniciando o display para o processo '{process_to_display.bot_name}'...")

    if process_to_display.process_type == "optimizer":
        # Launch the optimizer dashboard
        command = [sys.executable, "tui/optimizer_dashboard.py"]
        tui_env = os.environ.copy()
    else:
        # Launch the bot TUI
        tui_env = os.environ.copy()
        tui_env["BOT_NAME"] = process_to_display.bot_name
        tui_env["DOCKER_NETWORK_NAME"] = DOCKER_NETWORK_NAME
        tui_env["PROJECT_NAME"] = PROJECT_NAME
        command = [
            sys.executable, "tui/app.py",
            "--mode", process_to_display.bot_mode,
            "--container-id", process_to_display.container_id,
            "--host-port", str(process_to_display.host_port)
        ]

    try:
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

def _clear_tui_files():
    """Clears all JSON files from the .tui_files directory."""
    tui_dir = ".tui_files"
    if os.path.exists(tui_dir):
        # Glob for all possible json files generated by the optimizers
        files_to_delete = glob.glob(os.path.join(tui_dir, "*.json"))
        
        if files_to_delete:
            print("🗑️  Limpando arquivos de dashboard da otimização anterior...")
            for f in files_to_delete:
                try:
                    os.remove(f)
                except OSError as e:
                    print(f"⚠️  Aviso: Não foi possível deletar o arquivo {f}: {e}")
            print("✅ Limpeza concluída.")

def _save_best_params(bot_name: str):
    """
    Loads the completed study, finds the best trial, and saves its parameters.
    """
    if optuna is None:
        print("❌ A biblioteca 'optuna' não está instalada. Não foi possível salvar os melhores parâmetros.")
        return

    print("💾 Salvando os melhores parâmetros encontrados...")
    try:
        # We need to import these here as they are not top-level dependencies of run.py
        from jules_bot.optimizer import OPTIMIZE_OUTPUT_DIR, BEST_PARAMS_FILE

        study_name = f"optimization_{bot_name}"
        storage_url = f"sqlite:///{OPTIMIZE_OUTPUT_DIR}jules_bot_optimization.db"

        study = optuna.load_study(study_name=study_name, storage=storage_url)
        best_trial = study.best_trial

        print(f"🏆 Melhor trial: #{best_trial.number} -> Saldo Final: ${best_trial.value:,.2f}")

        # --- Save best trial summary for TUI ---
        tui_callback_dir = Path(".tui_files")
        tui_callback_dir.mkdir(exist_ok=True)
        best_trial_data = {
            "number": best_trial.number,
            "value": best_trial.value,
            "params": best_trial.params,
        }
        with open(tui_callback_dir / "best_trial_summary.json", "w") as f:
            json.dump(best_trial_data, f, indent=4)
        # --- End of new code ---

        with open(BEST_PARAMS_FILE, 'w') as f:
            f.write(f"# Best parameters for bot '{bot_name}' from study '{study_name}'\n")
            f.write(f"# Final Balance: {best_trial.value:.2f}\n\n")
            for key, value in best_trial.params.items():
                # This logic is copied from the original optimizer.py
                if "PROFIT_MULTIPLIER" in key:
                    base_profit = best_trial.params.get("STRATEGY_RULES_TARGET_PROFIT", 0.005)
                    original_key = key.replace("_PROFIT_MULTIPLIER", "_TARGET_PROFIT")
                    final_value = base_profit * value
                    f.write(f"{original_key.upper()}={final_value}\n")
                else:
                    f.write(f"{key.upper()}={value}\n")
        print(f"✅ Melhores parâmetros salvos com sucesso em '{BEST_PARAMS_FILE}'.")

    except ValueError:
        print("⚠️  Aviso: Nenhum trial foi completado com sucesso. Não foi possível determinar os melhores parâmetros.")
    except Exception as e:
        print(f"❌ Erro ao salvar os melhores parâmetros: {e}")

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
    prefix = bot_name.upper().replace('-', '_')
    bot_config_block = NEW_BOT_TEMPLATE.format(bot_name=bot_name, prefix=prefix)
    try:
        with open(env_file, "a", encoding='utf-8') as f:
            f.write(f"\n{bot_config_block}")
        print(f"✅ Bot '{bot_name}' adicionado com sucesso ao seu arquivo {env_file}!")
        print(f"   -> Agora, edite o arquivo e preencha com as chaves de API do bot.")
        print(f"   -> Lembre-se de preencher as chaves de TESTNET se for usar os comandos 'test' ou 'backtest'.")
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
    if not _ensure_env_is_running():
        raise typer.Exit(1)
    
    final_bot_name = _setup_bot_run(bot_name)
    print(f"🔎 Executando script de validação de dados para o bot '{final_bot_name}'...")
    if not run_command_in_container(["scripts/validate_trade_data.py", final_bot_name], final_bot_name):
        print("❌ Falha ao executar o script de validação.")
    else:
        print("✅ Script de validação concluído.")

def _get_optimizer_settings() -> dict:
    """Gets settings for the Genius Optimizer interactively."""
    if questionary is None:
        print("❌ A biblioteca 'questionary' é necessária para a otimização. Instale com 'pip install questionary'")
        raise typer.Exit(1)

    settings = {}
    print("\n--- 🧠 Configurações do Otimizador ---")

    trials_str = questionary.text(
        "Quantas combinações de parâmetros (trials) você deseja testar por regime?",
        default="50",
        validate=lambda text: text.isdigit() and int(text) > 0 or "Por favor, insira um número inteiro positivo."
    ).ask()
    if not trials_str: raise typer.Exit()
    settings["n_trials"] = int(trials_str)

    param_groups = {
        "USE_DYNAMIC_TRAILING_STOP": "Lógica de Trailing Stop Dinâmico",
        "USE_REVERSAL_BUY_STRATEGY": "Lógica de Compra por Reversão",
        "DYNAMIC_TRAIL": "Parâmetros do Trailing Stop",
        "REVERSAL_BUY": "Parâmetros da Compra por Reversão",
        "SIZING": "Parâmetros de Dimensionamento de Ordem",
        "DIFFICULTY": "Parâmetros de Dificuldade de Compra"
    }
    
    # Adicionando a opção "Otimizar Todos"
    all_param_keys = list(param_groups.keys())
    choices = [
        questionary.Choice(title=">> OTIMIZAR TODOS OS GRUPOS <<", value="ALL"),
        questionary.Separator(),
    ] + [
        questionary.Choice(title=v, value=k, checked=True) 
        for k, v in param_groups.items()
    ]

    selected_keys = questionary.checkbox(
        "Selecione os grupos de parâmetros para otimizar (use a barra de espaço para selecionar):",
        choices=choices,
    ).ask()


    if not selected_keys: 
        print("Nenhum grupo de parâmetros selecionado. Abortando.")
        raise typer.Exit()

    # Se "ALL" foi selecionado, usar todas as chaves de parâmetros
    if "ALL" in selected_keys:
        settings["active_params"] = {key: True for key in all_param_keys}
    else:
        settings["active_params"] = {key: True for key in selected_keys}
    return settings

def _run_optimizer(bot_name: str, days: int):
    """
    Launches the Genius Optimizer in a background container.
    """
    # Check if a bot with the same name is already running in test/trade mode.
    existing_bot_process = process_manager.get_bot_by_name(bot_name)
    if existing_bot_process and existing_bot_process.process_type == 'bot':
        print(f"❌ Erro: O bot '{bot_name}' já está em execução no modo '{existing_bot_process.bot_mode.upper()}'.")
        print("   Você não pode iniciar uma otimização para um bot que já está ativo.")
        print(f"   Para parar o bot, use: python run.py stop-bot --name {bot_name}")
        raise typer.Exit(1)

    # 1. Get settings from the user
    settings = _get_optimizer_settings()

    # 2. Confirm with the user
    print("\n--- 🧠 Iniciando Otimizador ---")
    print(f"   - Bot: {bot_name}, Dias: {days}, Trials por Regime: {settings['n_trials']}")
    print(f"   - Parâmetros Ativos: {list(settings['active_params'].keys())}")
    if not typer.confirm("Deseja continuar com a otimização?", default=True):
        raise typer.Exit()
    
    # 3. Clear old TUI files
    _clear_tui_files()

    # 4. Check if an optimizer for THIS bot is already running
    optimizer_process_name = f"{bot_name}-optimizer"
    existing_optimizer = process_manager.get_bot_by_name(optimizer_process_name)
    if existing_optimizer:
        print(f"⚠️  Um otimizador para o bot '{bot_name}' já está em execução (Container: {existing_optimizer.container_id[:12]}).")
        if typer.confirm("Deseja pará-lo e iniciar um novo?"):
            subprocess.run(SUDO_PREFIX + ["docker", "stop", existing_optimizer.container_id], capture_output=True)
            process_manager.remove_running_bot(optimizer_process_name)
            print("✅ Otimizador anterior parado.")
        else:
            print("👋 Operação cancelada.")
            raise typer.Exit()

    # 5. Launch the optimizer script in a background container
    print("\n⚙️  Iniciando a otimização em segundo plano...")
    active_params_json = json.dumps(settings['active_params'])
    command = [
        "scripts/run_genius_optimizer.py",
        bot_name,
        str(days),
        str(settings['n_trials']),
        active_params_json
    ]
    
    container_id = run_script_in_background_container(
        process_name=optimizer_process_name,
        context_bot_name=bot_name,
        command=command
    )

    if not container_id:
        print("❌ Falha ao iniciar o container do otimizador. Abortando.")
        raise typer.Exit(1)

    # 6. Register the running optimizer process
    process_manager.add_running_bot(
        bot_name=optimizer_process_name,
        container_id=container_id,
        bot_mode="optimizer",
        host_port=0,  # No port needed
        process_type="optimizer"
    )
    
    print(f"\n✅ Otimizador iniciado em segundo plano (Container: {container_id[:12]}).")
    print(f"   Para acompanhar o progresso, use: 'python run.py display'")
    print(f"   Para ver os logs, use:           'python run.py logs'")
    print(f"   Para parar o otimizador, use:      'python run.py stop-bot'")

@app.command()
def backtest(
    bot_name: Optional[str] = typer.Option(None, "--bot-name", "-n", help="O nome do bot para executar."),
    days: int = typer.Option(30, "--days", "-d", help="Número de dias de dados recentes para o backtest."),
    optimize: bool = typer.Option(False, "--optimize", help="Rodar o otimizador para encontrar os melhores parâmetros por regime de mercado."),
    use_best: bool = typer.Option(False, "--use-best", help="Rodar um backtest com os melhores parâmetros gerais encontrados pelo Genius Optimizer."),
    use_genius: bool = typer.Option(False, "--use-genius", help="[LEGACY] Rodar backtests usando os .env de resultados do Genius Optimizer para cada regime.")
):
    """Executa um backtest, com a opção de otimizar ou usar resultados da otimização."""
    final_bot_name = _setup_bot_run(bot_name)

    if sum([optimize, use_genius, use_best]) > 1:
        print("❌ Erro: As opções '--optimize', '--use-best' e '--use-genius' são mutuamente exclusivas.")
        raise typer.Exit(1)
    
    print("\n--- Etapa 1 de 2: Preparando dados históricos ---")
    if not run_command_in_container(["scripts/prepare_backtest_data.py", str(days)], final_bot_name):
        print("❌ Falha na preparação dos dados. Abortando backtest.")
        return

    if optimize:
        _run_optimizer(final_bot_name, days)
        raise typer.Exit()

    # This variable will hold the final decision on whether to use the best params.
    # It can be set by the flag or by the interactive prompt.
    should_use_best = use_best
    best_params_file = "optimize/genius/.env.best_overall"

    # --- Interactive prompt if no mode is specified ---
    if not any([optimize, use_genius, use_best]):
        if questionary is None:
            print("⚠️  A biblioteca 'questionary' não está instalada. Rodando com parâmetros padrão.")
        else:
            if not os.path.exists(best_params_file):
                print("ℹ️  Arquivo de melhores parâmetros não encontrado. Rodando com parâmetros padrão do .env.")
            else:
                choice = questionary.select(
                    "Qual conjunto de parâmetros você gostaria de usar para o backtest?",
                    choices=[
                        questionary.Choice("Padrão (do arquivo .env)", "default"),
                        questionary.Choice("Melhores Otimizados (encontrados pelo Genius Optimizer)", "best"),
                    ],
                    default="default"
                ).ask()

                if choice is None: # User pressed Ctrl+C
                    raise typer.Exit()
                if choice == "best":
                    should_use_best = True

    # --- Execution Logic ---
    extra_env_files = []
    if should_use_best:
        print("\n--- Etapa 2 de 2: Rodando backtest com os MELHORES parâmetros encontrados ---")
        if not os.path.exists(best_params_file):
            print(f"❌ Arquivo de melhores parâmetros '{best_params_file}' não encontrado.")
            print("   Você precisa rodar a otimização primeiro com a flag '--optimize'.")
            raise typer.Exit(1)

        print(f"   (usando arquivo de parâmetros: {best_params_file})")
        extra_env_files.append(best_params_file)

    elif use_genius:
        print("\n--- Etapa 2 de 2: Rodando backtests com os resultados do Genius Optimizer ---")
        genius_dir = "optimize/genius"
        env_files = glob.glob(os.path.join(genius_dir, ".env.*"))

        if not env_files:
            print(f"❌ Nenhum arquivo de resultado do Genius Optimizer (.env.*) encontrado em '{genius_dir}'.")
            print("   Você precisa rodar a otimização primeiro com a flag '--optimize'.")
            raise typer.Exit(1)

        print(f"✅ Encontrados {len(env_files)} arquivos de resultado. Rodando um backtest para cada um...")

        for env_file in sorted(env_files):
            regime_name = os.path.basename(env_file).replace('.env.', '').upper()
            print("\n" + "="*80)
            print(f"⚡️ INICIANDO BACKTEST PARA O REGIME: {regime_name} ⚡️")
            print(f"   (usando arquivo de parâmetros: {env_file})")
            print("="*80 + "\n")

            success = run_command_in_container(
                ["scripts/run_backtest.py", str(days)],
                final_bot_name,
                extra_env_files=[env_file]
            )
            if not success:
                print(f"⚠️  Backtest para o regime {regime_name} falhou. Verifique os logs acima.")
            print(f"\n--- ✅ Backtest para o regime {regime_name} finalizado ---")

        print("\n🎉 Todos os backtests baseados no Genius Optimizer foram concluídos.")
        raise typer.Exit()
    else:
        print(f"\n--- Etapa 2 de 2: Rodando backtest padrão para {days} dias ---")

    # Common execution for default and --use-best
    success = run_command_in_container(
        ["scripts/run_backtest.py", str(days)],
        final_bot_name,
        extra_env_files=extra_env_files if extra_env_files else None
    )
    if not success:
        print("❌ Falha na execução do backtest.")
    else:
        print("\n✅ Backtest finalizado com sucesso.")

@app.command("clean")
def clean():
    """
    Limpa o projeto de arquivos de cache do Python (__pycache__, .pyc).
    """
    print("🧹 Limpando arquivos de cache do Python...")
    count_files = 0
    count_dirs = 0
    gitignore_path = ".gitignore"
    pycache_ignored = False
    if os.path.exists(gitignore_path):
        with open(gitignore_path, "r") as f:
            if any("__pycache__" in line for line in f):
                pycache_ignored = True
    
    if not pycache_ignored:
        print("   -> Adicionando '__pycache__/' ao .gitignore para prevenir futuros problemas...")
        with open(gitignore_path, "a") as f:
            f.write("\n\n# Python cache files\n__pycache__/\n")

    for root, dirs, files in os.walk("."):
        for file in files:
            if file.endswith(".pyc"):
                full_path = os.path.join(root, file)
                try:
                    os.remove(full_path)
                    count_files += 1
                except OSError as e:
                    print(f"❌ Erro ao remover o arquivo {full_path}: {e}")

        if "__pycache__" in dirs:
            full_path = os.path.join(root, "__pycache__")
            try:
                shutil.rmtree(full_path)
                count_dirs += 1
                dirs.remove('__pycache__')
            except OSError as e:
                print(f"❌ Erro ao remover o diretório {full_path}: {e}")
    
    print(f"✅ Limpeza concluída. Removidos {count_files} arquivos .pyc e {count_dirs} diretórios __pycache__.")

if __name__ == "__main__":
    app()
