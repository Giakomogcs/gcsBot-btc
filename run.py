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


@app.command()
def trade():
    """Inicia o bot em modo de negociação (live)."""
    mode = "trade"
    print(f"🚀 Iniciando o bot em modo '{mode.upper()}'...")
    _run_in_container(
        command=["jules_bot/main.py"],
        env_vars={"BOT_MODE": mode}
    )

@app.command()
def test():
    """Inicia o bot em modo de teste (testnet), limpando o estado anterior."""
    mode = "test"

    print("🗑️  Limpando o estado de teste anterior para garantir uma sessão limpa...")
    # Executa o script de limpeza de forma não-interativa.
    # A função `_run_in_container` retorna True em caso de sucesso (código de saída 0).
    success = _run_in_container(
        command=["scripts/clear_testnet_trades.py"]
    )

    if not success:
        print("❌ Falha ao limpar o estado de teste. Abortando o início do bot.")
        # Usamos typer.Exit para terminar o script com um código de erro.
        raise typer.Exit(code=1)

    print(f"✅ Estado anterior limpo. Iniciando o bot em modo '{mode.upper()}'...")
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
def dashboard(
    mode: str = typer.Option(
        "test", "--mode", "-m", help="O modo de operação a ser monitorado ('trade' ou 'test')."
    )
):
    """Inicia a nova Interface de Usuário (TUI) para monitoramento e controle."""
    print(f"🚀 Iniciando o dashboard para o modo '{mode.upper()}'...")
    print("   Lembre-se que o bot (usando 'trade' ou 'test') deve estar rodando em outro terminal.")

    command_to_run = ["tui/app.py", "--mode", mode]

    _run_in_container(
        command=command_to_run,
        interactive=True
    )
    print("\n✅ Dashboard encerrado.")


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
