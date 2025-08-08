import os
import sys
import shutil
import typer
import subprocess
from typing import Optional

app = typer.Typer()

# --- Lógica de Detecção do Docker Compose ---

def get_docker_compose_command():
    """
    Verifica se 'docker-compose' (V1) ou 'docker compose' (V2) está disponível.
    """
    if shutil.which("docker-compose"):
        return ["docker-compose"]
    elif shutil.which("docker"):
        try:
            result = subprocess.run(["docker", "compose", "--version"], capture_output=True, text=True, check=True)
            if "Docker Compose version" in result.stdout:
                return ["docker", "compose"]
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass
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
    if run_docker_command(["up", "--build", "-d"], capture_output=True):
        print("✅ Serviços iniciados com sucesso.")
        print("   O container 'app' está rodando em modo idle.")
        print("   Use `python run.py trade`, `test`, ou `backtest` para executar tarefas.")

@app.command("stop")
def stop():
    """Para e remove todos os serviços."""
    print("🔥 Parando serviços Docker...")
    if run_docker_command(["down"], capture_output=True):
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

def _run_in_container(command: list, env_vars: dict = {}):
    """Executa um comando Python dentro do container 'app', mostrando o output em tempo real."""
    try:
        docker_cmd = get_docker_compose_command()
        
        exec_cmd = docker_cmd + ["exec"]
        for key, value in env_vars.items():
            exec_cmd.extend(["-e", f"{key}={value}"])
        
        # Comando final a ser executado no container
        container_command = ["app", "python"] + command
        exec_cmd.extend(container_command)
        
        print(f"   (executando: `{' '.join(docker_cmd)} exec {' '.join(container_command)}`)")

        # Usamos Popen para streaming de output em tempo real
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
    """Inicia o bot em modo de negociação (live) dentro do container."""
    print("🚀 Iniciando o bot em modo 'TRADE'...")
    _run_in_container(
        command=["jules_bot/main.py"],
        env_vars={"BOT_MODE": "trade"}
    )

@app.command()
def test():
    """Inicia o bot em modo de teste (testnet) dentro do container."""
    print("🚀 Iniciando o bot em modo 'TEST'...")
    _run_in_container(
        command=["jules_bot/main.py"],
        env_vars={"BOT_MODE": "test"}
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
    if not _run_in_container(["collectors/core_price_collector.py", str(days)]):
        print("❌ Falha na preparação dos dados. Abortando backtest.")
        return

    print("\n--- Etapa 2 de 2: Rodando o backtest ---")
    if not _run_in_container(["scripts/run_backtest.py"]):
        print("❌ Falha na execução do backtest.")
        return
        
    print("\n✅ Backtest finalizado com sucesso.")


if __name__ == "__main__":
    app()
