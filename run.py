import os
import sys
import shutil
import typer
import subprocess
from typing import Optional

from jules_bot.database.postgres_manager import PostgresManager
from jules_bot.utils.config_manager import config_manager

app = typer.Typer()

# --- Lógica de Detecção do Docker Compose ---

def get_docker_compose_command():
    """
    Verifica se 'docker-compose' (V1) ou 'docker compose' (V2) está disponível.
    Adiciona 'sudo' se o usuário não for root para evitar problemas de permissão.
    """
    # Lista de comandos base. Adiciona 'sudo' se não formos o usuário root.
    base_cmd = []
    try:
        # os.geteuid() não existe no Windows, então tratamos o erro.
        # No Windows, o gerenciamento de permissões do Docker é diferente e geralmente não requer sudo.
        if os.geteuid() != 0:
            base_cmd = ["sudo"]
    except AttributeError:
        # Se geteuid não existe, estamos provavelmente no Windows. Não fazemos nada.
        pass

    # Tenta encontrar um comando docker-compose válido
    if shutil.which("docker-compose"):
        return base_cmd + ["docker-compose"]
    elif shutil.which("docker"):
        try:
            # Constrói o comando de teste completo (ex: ['sudo', 'docker', 'compose', '--version'])
            test_command = base_cmd + ["docker", "compose", "--version"]
            result = subprocess.run(test_command, capture_output=True, text=True, check=True)
            if "Docker Compose version" in result.stdout:
                return base_cmd + ["docker", "compose"]
        except (subprocess.CalledProcessError, FileNotFoundError):
            # Se o teste falhar, continuamos para o erro final
            pass
    
    # Se nenhuma versão do comando foi encontrada
    raise FileNotFoundError("Could not find a valid 'docker-compose' or 'docker compose' command. Please ensure Docker is installed and in your PATH.")

def run_docker_command(command_args: list, **kwargs):
    """Helper para executar comandos docker e lidar com erros."""
    try:
        base_command = get_docker_compose_command()
        full_command = base_command + command_args
        print(f"   (usando comando: `{' '.join(full_command)}`)")
        # Para comandos de ambiente, não precisamos de output em tempo real, então 'run' é ok.
        subprocess.run(full_command, check=True, **kwargs)
        return True
    except FileNotFoundError as e:
        print(f"❌ Erro: {e}")
    except subprocess.CalledProcessError as e:
        print(f"❌ Erro ao executar comando. Código de saída: {e.returncode}")
        if e.stderr:
            # Em alguns casos, o stderr é usado para output normal, então decodificamos se possível
            print(f"   Stderr:\n{e.stderr.decode('utf-8', 'ignore')}")
        if e.stdout:
            print(f"   Stdout:\n{e.stdout.decode('utf-8', 'ignore')}")
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

        for key, value in env_vars.items():
            exec_cmd.extend(["-e", f"{key}={value}"])

        # Comando final a ser executado no container
        container_command = ["app", "python"] + command
        exec_cmd.extend(container_command)

        print(f"   (executando: `{' '.join(exec_cmd)}`)")

        if interactive:
            # Para TUIs, precisamos que o processo anexe ao terminal do host.
            # `subprocess.run` sem capturar output e com `check=False` é ideal.
            # Deixamos o processo filho controlar o terminal.
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


@app.command()
def trade():
    """Inicia a API em background e o bot em modo de negociação (live)."""
    mode = "trade"
    print(f"🚀 Iniciando o bot em modo '{mode.upper()}' com API...")

    print("\n--- Etapa 1 de 2: Iniciando a API em segundo plano ---")
    if not _run_in_container(
        command=["api/main.py"],
        env_vars={"BOT_MODE": mode},
        detached=True
    ):
        print("❌ Falha ao iniciar a API. Abortando.")
        return

    print("   Aguardando 3 segundos para a API inicializar...")
    time.sleep(3)

    print(f"\n--- Etapa 2 de 2: Iniciando o bot em modo '{mode.upper()}' ---")
    _run_in_container(
        command=["jules_bot/main.py"],
        env_vars={"BOT_MODE": mode}
    )

@app.command()
def test():
    """Inicia a API em background e o bot em modo de teste (testnet)."""
    mode = "test"
    print(f"🚀 Iniciando o bot em modo '{mode.upper()}' com API...")

    print("\n--- Etapa 1 de 2: Iniciando a API em segundo plano ---")
    if not _run_in_container(
        command=["api/main.py"],
        env_vars={"BOT_MODE": mode},
        detached=True
    ):
        print("❌ Falha ao iniciar a API. Abortando.")
        return

    print("   Aguardando 3 segundos para a API inicializar...")
    time.sleep(3)

    print(f"\n--- Etapa 2 de 2: Iniciando o bot em modo '{mode.upper()}' ---")
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
    print(f"🚀 Iniciando execução de backtest para {days} dias...")

    print("\n--- Etapa 1 de 2: Preparando dados ---")
    if not _run_in_container(["scripts/prepare_backtest_data.py", str(days)]):
        print("❌ Falha na preparação dos dados. Abortando backtest.")
        return

    print("\n--- Etapa 2 de 2: Rodando o backtest ---")
    if not _run_in_container(["scripts/run_backtest.py", str(days)]):
        print("❌ Falha na execução do backtest.")
        return

    print("\n✅ Backtest finalizado com sucesso.")

@app.command()
def ui():
    """Inicia a interface de usuário (TUI) para monitorar e controlar o bot."""
    print("🖥️  Iniciando a Interface de Usuário (TUI)...")
    print("   Lembre-se que o bot (usando 'trade' ou 'test') deve estar rodando em outro terminal.")
    _run_in_container(
        command=["jules_bot/ui/app.py"],
        interactive=True
    )

@app.command()
def api(
    mode: str = typer.Option(
        "live", "--mode", "-m", help="O modo de operação para a API (ex: 'live', 'test')."
    )
):
    """Inicia o serviço da API, configurando o BOT_MODE."""
    print(f"🚀 Iniciando o serviço de API em modo '{mode.upper()}'...")
    _run_in_container(
        command=["api/main.py"],
        env_vars={"BOT_MODE": mode},
        interactive=True
    )

import time

@app.command()
def dashboard(
    mode: str = typer.Argument(..., help="O modo de operação a ser monitorado (ex: 'trade', 'test').")
):
    """Inicia a API em segundo plano e a TUI em primeiro plano para monitoramento."""
    print(f"🚀 Iniciando o dashboard para o modo '{mode.upper()}'...")

    print("\n--- Etapa 1 de 2: Iniciando a API em segundo plano ---")
    if not _run_in_container(
        command=["api/main.py"],
        env_vars={"BOT_MODE": mode},
        detached=True
    ):
        print("❌ Falha ao iniciar a API. Abortando.")
        return

    print("   Aguardando 3 segundos para a API inicializar...")
    time.sleep(3)

    print("\n--- Etapa 2 de 2: Iniciando a Interface de Usuário (TUI) ---")
    if not _run_in_container(
        command=["jules_bot/ui/app.py"],
        interactive=True
    ):
        print("❌ A TUI foi encerrada ou falhou ao iniciar.")

    print("\n✅ Dashboard encerrado.")
    print("   Lembre-se que o serviço da API ainda pode estar rodando em segundo plano.")
    print("   Use `docker ps` para verificar e `docker kill <container_id>` se necessário.")


@app.command("clear-backtest-trades")
def clear_backtest_trades():
    """Deletes all trades from the 'backtest' environment in the database."""
    print("🗑️  Attempting to clear all backtest trades from the database...")
    _run_in_container(
        command=["scripts/clear_trades_measurement.py", "backtest"],
        interactive=True
    )

@app.command("clear-testnet-trades")
def clear_testnet_trades():
    """Deletes all trades from the 'test' environment in the database."""
    print("🗑️  Attempting to clear all testnet trades from the database...")
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
    print("🗑️  Attempting to wipe the database...")
    print("   This will run the script inside the container.")

    _run_in_container(
        command=["scripts/wipe_database.py"],
        interactive=True
    )


if __name__ == "__main__":
    app()
