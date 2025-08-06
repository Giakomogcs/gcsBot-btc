# #############################################################################
# # ATENÇÃO: ESTE SCRIPT (run.py) ESTÁ OBSOLETO E NÃO É MAIS UTILIZADO.       #
# #############################################################################
# #
# # O gerenciamento do projeto agora é feito exclusivamente através do
# # script PowerShell `manage.ps1`. Ele oferece uma interface de comando
# # mais robusta e centralizada para todas as operações do bot, incluindo
# # setup, execução de backtests, otimização e operações ao vivo.
# #
# # Por favor, utilize `.\manage.ps1` para todas as interações com o bot.
# #
# #############################################################################


# run.py (VERSÃO 3.2 - Usando Docker Compose V2)

import subprocess
import os
import sys
import shutil
import json
import time
from dotenv import load_dotenv
from datetime import datetime, timezone
from dateutil.parser import isoparse

# --- Configuração do Projeto ---
DOCKER_IMAGE_NAME = "gcsbot"
KAGGLE_DATA_FILE = os.path.join("data", "kaggle_btc_1m_bootstrap.csv")
ENV_FILE = ".env"
ENV_EXAMPLE_FILE = ".env.example"
MODEL_METADATA_FILE = os.path.join("data", "model_metadata.json")
OPTIMIZER_STATUS_FILE = os.path.join("logs", "optimizer_status.json")
TRADING_STATUS_FILE = os.path.join("logs", "trading_status.json")
# -----------------------------

def print_color(text, color="green"):
    """Imprime texto colorido no terminal."""
    colors = {"green": "\033[92m", "yellow": "\033[93m", "red": "\033[91m", "blue": "\033[94m", "end": "\033[0m"}
    print(f"{colors.get(color, colors['green'])}{text}{colors['end']}")

def run_command(command, shell=True, capture_output=False, check=False):
    """Executa um comando no shell."""
    print_color(f"\n> Executando: {command}", "blue")
    try:
        if not capture_output:
            process = subprocess.Popen(command, shell=shell, text=True, stdout=sys.stdout, stderr=sys.stderr)
            process.wait()
            if check and process.returncode != 0:
                raise subprocess.CalledProcessError(process.returncode, command)
            return process
        else:
            result = subprocess.run(command, shell=shell, capture_output=True, text=True, encoding='utf-8', check=check)
            return result
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print_color(f"ERRO ao executar o comando: {command}\n{e}", "red")
        sys.exit(1)

def check_docker_running():
    print_color("Verificando se o Docker está em execução...", "yellow")
    try:
        subprocess.run("docker info", shell=True, check=True, capture_output=True)
        print_color("Docker está ativo e pronto.", "green")
    except (subprocess.CalledProcessError, FileNotFoundError):
        print_color("ERRO: Docker Desktop não parece estar em execução.", "red"); sys.exit(1)

def check_env_file():
    print_color("Verificando arquivo de configuração .env...", "yellow")
    if not os.path.exists(ENV_FILE):
        print_color(f"Arquivo .env não encontrado. Copiando de {ENV_EXAMPLE_FILE}...", "yellow")
        if not os.path.exists(ENV_EXAMPLE_FILE):
             print_color(f"ERRO: {ENV_EXAMPLE_FILE} também não encontrado.", "red"); sys.exit(1)
        shutil.copy(ENV_EXAMPLE_FILE, ENV_FILE)
        print_color("IMPORTANTE: Abra o arquivo .env e preencha suas chaves de API.", "red"); sys.exit(1)
    print_color("Arquivo .env encontrado.", "green")

def initial_setup():
    print_color("--- Iniciando Setup e Verificação do Ambiente ---", "blue")
    check_env_file()
    os.makedirs("data", exist_ok=True)
    os.makedirs("logs", exist_ok=True)
    run_command(f"\"{sys.executable}\" -m pip install -r requirements.txt", check=True)
    print_color("--- Setup Concluído com Sucesso ---", "green")

def start_optimizer():
    """Inicia o processo de otimização em um container Docker em modo background."""
    check_docker_running()
    print_color("--- Iniciando Otimização (Modo Background) ---", "blue")
    # <<< CORRIGIDO AQUI
    run_command("docker compose up -d --build app", check=True)
    print_color("Otimização iniciada em segundo plano com sucesso!", "green")
    print_color("Para acompanhar o progresso, use o comando:", "yellow")
    print_color("python3 run.py display", "blue")
    print_color("Para ver os logs completos, use o comando:", "yellow")
    print_color("python3 run.py logs", "blue")

def start_bot(mode):
    check_docker_running()
    print_color(f"--- Iniciando Bot em Modo '{mode.upper()}' ---", "blue")
    # <<< CORRIGIDO AQUI
    run_command(f"MODE={mode} docker compose up -d --build app", check=True)

    if mode in ['test', 'trade']:
        print_color(f"Bot no modo '{mode}' iniciado em segundo plano.", "green")
        print_color("Para ver os logs, use: python3 run.py logs", "yellow")

def stop_all():
    check_docker_running()
    print_color("--- Parando e Removendo TODOS os Containers do Bot ---", "yellow")
    # <<< CORRIGIDO AQUI
    run_command("docker compose down", check=True)
    print_color("Containers parados e removidos com sucesso.", "green")

def show_logs():
    check_docker_running()
    print_color("Anexando aos logs do container 'app'. Pressione CTRL+C para sair.", "green")
    try:
        # <<< CORRIGIDO AQUI
        subprocess.run("docker compose logs -f app", shell=True)
    except KeyboardInterrupt: print_color("\n\nDesanexado dos logs.", "yellow")

def show_display():
    """Mostra o painel de otimização lendo o arquivo de status."""
    from gcs_bot.core.display_manager import display_optimization_dashboard
    
    # <<< CORRIGIDO AQUI
    result = run_command("docker compose ps -q app", capture_output=True)
    if not result.stdout.strip():
        print_color("O container de otimização 'app' não está em execução.", "red")
        print_color("Inicie-o com: python3 run.py optimize", "yellow")
        return

    print_color("Mostrando painel de otimização. Pressione CTRL+C para sair.", "green")
    try:
        while True:
            if os.path.exists(OPTIMIZER_STATUS_FILE):
                try:
                    with open(OPTIMIZER_STATUS_FILE, 'r') as f:
                        status_data = json.load(f)
                    display_optimization_dashboard(status_data)
                except (json.JSONDecodeError, KeyError) as e:
                    print(f"Aguardando arquivo de status válido... Erro: {e}")
            else:
                print("Aguardando o otimizador iniciar e criar o arquivo de status...")
            
            time.sleep(2)
    except KeyboardInterrupt:
        print_color("\nPainel finalizado.", "yellow")

def show_trading_display():
    """Mostra o painel de trading lendo o arquivo de status."""
    from gcs_bot.core.display_manager import display_trading_dashboard

    result = run_command("docker compose ps -q app", capture_output=True)
    if not result.stdout.strip():
        print_color("O container do bot 'app' não está em execução.", "red")
        print_color("Inicie-o com: python3 run.py trade", "yellow")
        return

    print_color("Mostrando painel de trading. Pressione CTRL+C para sair.", "green")
    try:
        while True:
            if os.path.exists(TRADING_STATUS_FILE):
                try:
                    with open(TRADING_STATUS_FILE, 'r') as f:
                        status_data = json.load(f)
                    display_trading_dashboard(status_data)
                except (json.JSONDecodeError, KeyError) as e:
                    print(f"Aguardando arquivo de status válido... Erro: {e}")
            else:
                print("Aguardando o bot iniciar e criar o arquivo de status...")

            time.sleep(5)
    except KeyboardInterrupt:
        print_color("\nPainel finalizado.", "yellow")

def main():
    if len(sys.argv) < 2:
        print_color("Uso: python3 run.py [comando]", "blue")
        print("Comandos disponíveis:")
        print("  setup             - Instala dependências e prepara o ambiente.")
        print("  optimize          - Roda a otimização em SEGUNDO PLANO.")
        print("  display           - Mostra o PAINEL da otimização em execução.")
        print("  trade             - Roda o bot em modo de trade em SEGUNDO PLANO.")
        print("  show_trading      - Mostra o PAINEL do bot de trade em execução.")
        print("  backtest          - Roda um backtest rápido com o modelo atual.")
        print("  stop              - Para e remove TODOS os containers do bot.")
        print("  logs              - Mostra os logs brutos de um container em execução.")
        return

    command = sys.argv[1].lower()
    
    if command == "setup": initial_setup()
    elif command == "optimize": start_optimizer()
    elif command == "display": show_display()
    elif command == "trade": start_bot('trade')
    elif command == "show_trading": show_trading_display()
    elif command == "backtest": start_bot('backtest')
    elif command == "stop": stop_all()
    elif command == "logs": show_logs()
    else: print_color(f"Comando '{command}' não reconhecido.", "red")

if __name__ == "__main__":
    main()