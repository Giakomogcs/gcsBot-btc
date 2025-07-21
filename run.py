# run.py (VERSÃO 3.0 - Com Display Desacoplado)

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
# <<< NOVO >>> Arquivo de status para o display
OPTIMIZER_STATUS_FILE = os.path.join("data", "optimizer_status.json")
# -----------------------------

def print_color(text, color="green"):
    """Imprime texto colorido no terminal."""
    colors = {"green": "\033[92m", "yellow": "\033[93m", "red": "\033[91m", "blue": "\033[94m", "end": "\033[0m"}
    print(f"{colors.get(color, colors['green'])}{text}{colors['end']}")

def run_command(command, shell=True, capture_output=False, check=False):
    """Executa um comando no shell."""
    print_color(f"\n> Executando: {command}", "blue")
    try:
        # Usar Popen para streaming de output se não for capture_output
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
    run_command(f"\"{sys.executable}\" -m pip install -r requirements.txt", check=True)
    print_color("--- Setup Concluído com Sucesso ---", "green")

def docker_build():
    check_docker_running()
    print_color(f"--- Construindo Imagem Docker: {DOCKER_IMAGE_NAME} ---", "blue")
    run_command(f"docker build -t {DOCKER_IMAGE_NAME} .", check=True)
    print_color("--- Imagem Docker Construída com Sucesso ---", "green")

def model_guardian():
    print_color("\n--- 🛡️ Guardião do Modelo: Verificando Status 🛡️ ---", "blue")
    if not os.path.exists(MODEL_METADATA_FILE):
        print_color("AVISO: Nenhum modelo encontrado. Rode 'python run.py optimize' primeiro.", "yellow")
        sys.exit(1)
    try:
        with open(MODEL_METADATA_FILE, 'r') as f: metadata = json.load(f)
        valid_until = isoparse(metadata.get("valid_until"))
        if datetime.now(timezone.utc) > valid_until:
            print_color(f"AVISO: O modelo atual expirou. Rode 'python run.py optimize' para criar um novo.", "red")
            sys.exit(1)
        else:
            print_color(f"✅ Modelo está válido. Expira em: {(valid_until - datetime.now(timezone.utc)).days} dias.", "green")
    except Exception as e:
        print_color(f"Erro ao ler metadados do modelo: {e}. Rode 'optimize' por segurança.", "red")
        sys.exit(1)

def start_optimizer():
    """Inicia o processo de otimização em um container Docker em modo background."""
    check_docker_running()
    container_name = "gcsbot-optimizer"
    print_color(f"--- Iniciando Otimização (Modo Background) no container '{container_name}' ---", "blue")

    # Garante que um container antigo seja removido para evitar conflitos
    run_command(f"docker rm -f {container_name}", capture_output=True)

    # Mapeia os volumes de 'data' e 'logs' para persistir os resultados e logs
    data_volume = f"-v \"{os.path.abspath('data')}:/app/data\""
    logs_volume = f"-v \"{os.path.abspath('logs')}:/app/logs\""

    # Comando para rodar o container em modo 'optimize'
    # -d: detached (background)
    # --restart unless-stopped: reinicia o container a menos que seja parado manualmente
    # --name: nome do container
    # --env-file: usa o .env para as variáveis de ambiente
    # -e MODE=optimize: define o modo de operação
    command = (
        f"docker run -d --restart unless-stopped --name {container_name} "
        f"--env-file .env -e MODE=optimize {data_volume} {logs_volume} {DOCKER_IMAGE_NAME}"
    )

    run_command(command, check=True)
    print_color("Otimização iniciada em segundo plano com sucesso!", "green")
    print_color("Para acompanhar o progresso, use o comando:", "yellow")
    print_color("python run.py display", "blue")
    print_color("Para ver os logs completos, use o comando:", "yellow")
    print_color("python run.py logs", "blue")

def start_bot(mode):
    check_docker_running()
    container_name = f"gcsbot-{mode}"
    print_color(f"--- Iniciando Bot em Modo '{mode.upper()}' no container '{container_name}' ---", "blue")
    run_command(f"docker rm -f {container_name}", capture_output=True)
    data_volume = f"-v \"{os.path.abspath('data')}:/app/data\""; logs_volume = f"-v \"{os.path.abspath('logs')}:/app/logs\""
    
    if mode in ['test', 'trade']:
        run_params = "-d --restart always"
        detached = True
    else: # backtest
        run_params = "--rm -it"
        detached = False
        
    command = f"docker run {run_params} --name {container_name} --env-file .env -e MODE={mode} {data_volume} {logs_volume} {DOCKER_IMAGE_NAME}"
    run_command(command, check=True)

    if detached:
        print_color(f"Bot no modo '{mode}' iniciado em segundo plano.", "green")
        print_color("Para ver os logs, use: python run.py logs", "yellow")

def stop_all():
    check_docker_running()
    print_color("--- Parando e Removendo TODOS os Containers do Bot ---", "yellow")
    result = run_command("docker ps -a --filter \"name=gcsbot-\" --format \"{{.Names}}\"", capture_output=True)
    containers = [c for c in result.stdout.strip().split('\n') if c]
    if not containers: print_color("Nenhum container do bot encontrado.", "green"); return
    for container in containers:
        print_color(f"Parando e removendo o container {container}...")
        run_command(f"docker stop {container}", capture_output=True)
        run_command(f"docker rm {container}", capture_output=True)
    print_color("Containers parados e removidos com sucesso.", "green")

def show_logs():
    check_docker_running()
    # <<< ALTERADO >>> Procura por qualquer container gcsbot
    result = run_command("docker ps -q --filter \"name=gcsbot-\"", capture_output=True)
    if not result.stdout.strip():
        print_color("Nenhum container do bot está em execução.", "red")
        return

    # Pede ao usuário para escolher se houver mais de um
    containers = run_command("docker ps --format \"{{.Names}}\" --filter \"name=gcsbot-\"", capture_output=True).stdout.strip().split('\n')
    container_name = containers[0]
    if len(containers) > 1:
        print_color("Múltiplos containers em execução. Qual você quer ver?", "yellow")
        for i, name in enumerate(containers):
            print(f"  {i+1}) {name}")
        choice = input("Digite o número: ")
        try:
            container_name = containers[int(choice) - 1]
        except (ValueError, IndexError):
            print_color("Seleção inválida.", "red")
            return

    print_color(f"Anexando aos logs do container '{container_name}'. Pressione CTRL+C para sair.", "green")
    try:
        subprocess.run(f"docker logs -f {container_name}", shell=True)
    except KeyboardInterrupt: print_color("\n\nDesanexado dos logs.", "yellow")

# <<< NOVO >>> Função para mostrar o painel de otimização
def show_display():
    """Mostra o painel de otimização lendo o arquivo de status."""
    from src.display_manager import display_optimization_dashboard # Importa a função de display
    
    container_name = "gcsbot-optimizer"
    result = run_command(f"docker ps -q --filter \"name={container_name}\"", capture_output=True)
    if not result.stdout.strip():
        print_color(f"O container de otimização '{container_name}' não está em execução.", "red")
        print_color("Inicie-o com: python run.py optimize", "yellow")
        return

    print_color("Mostrando painel de otimização. Pressione CTRL+C para sair.", "green")
    try:
        while True:
            if os.path.exists(OPTIMIZER_STATUS_FILE):
                try:
                    with open(OPTIMIZER_STATUS_FILE, 'r') as f:
                        status_data = json.load(f)
                    # Passa o dicionário de dados para a função de display
                    display_optimization_dashboard(status_data)
                except (json.JSONDecodeError, KeyError) as e:
                    print(f"Aguardando arquivo de status válido... Erro: {e}")
            else:
                print("Aguardando o otimizador iniciar e criar o arquivo de status...")
            
            time.sleep(2) # Intervalo de atualização
    except KeyboardInterrupt:
        print_color("\nPainel finalizado.", "yellow")

def show_status():
    print_color("\n--- 🔍 Verificando Status do Modelo 🔍 ---", "blue")
    if not os.path.exists(MODEL_METADATA_FILE):
        print_color("Status: NENHUM MODELO ENCONTRADO.", "red"); return
    try:
        with open(MODEL_METADATA_FILE, 'r') as f: metadata = json.load(f)
        valid_until = isoparse(metadata.get("valid_until"))
        last_opt = isoparse(metadata.get("last_optimization_date"))
        if datetime.now(timezone.utc) > valid_until: print_color("Status: EXPIRADO", "red")
        else: print_color("Status: VÁLIDO", "green")
        print(f"  - Última Otimização: {last_opt.strftime('%Y-%m-%d %H:%M')}")
        print(f"  - Válido Até:          {valid_until.strftime('%Y-%m-%d %H:%M')}")
    except Exception as e: print_color(f"Status: ERRO AO LER METADADOS ({e})", "red")


def main():
    if len(sys.argv) < 2:
        print_color("Uso: python run.py [comando]", "blue")
        print("Comandos disponíveis:")
        print("  setup        - Instala dependências e prepara o ambiente.")
        print("  build        - Constrói (ou reconstrói) a imagem Docker.")
        print("  optimize     - Roda a otimização em SEGUNDO PLANO.")
        print("  display      - Mostra o PAINEL da otimização em execução.")
        print("  backtest     - Roda um backtest rápido com o modelo atual.")
        print("  test / trade - Roda o bot (em segundo plano).")
        print("  status       - Verifica a validade do modelo atual.")
        print("  stop         - Para e remove TODOS os containers do bot.")
        print("  logs         - Mostra os logs brutos de um container em execução.")
        return

    command = sys.argv[1].lower()
    
    if command == "setup": initial_setup()
    elif command == "build": docker_build()
    elif command == "optimize": start_optimizer()
    elif command == "display": show_display() # <<< NOVO COMANDO
    elif command == "status": show_status()
    elif command in ["test", "trade"]:
        model_guardian()
        start_bot(command)
    elif command == "backtest":
        start_bot(command)
    elif command == "stop": stop_all()
    elif command == "logs": show_logs()
    else: print_color(f"Comando '{command}' não reconhecido.", "red")

if __name__ == "__main__":
    main()