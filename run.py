# run.py (VERSÃO 2.0 - COM GUARDIÃO DO MODELO)

import subprocess
import os
import sys
import shutil
import json
from dotenv import load_dotenv
from datetime import datetime, timezone
from dateutil.parser import isoparse

# --- Configuração do Projeto ---
DOCKER_IMAGE_NAME = "gcsbot"
KAGGLE_DATA_FILE = os.path.join("data", "kaggle_btc_1m_bootstrap.csv")
ENV_FILE = ".env"
ENV_EXAMPLE_FILE = ".env.example"
# <<< PASSO 1: Adicionar o caminho para o novo arquivo de metadados >>>
MODEL_METADATA_FILE = os.path.join("data", "model_metadata.json")
# -----------------------------

def print_color(text, color="green"):
    """Imprime texto colorido no terminal."""
    colors = {
        "green": "\033[92m", "yellow": "\033[93m", "red": "\033[91m",
        "blue": "\033[94m", "end": "\033[0m",
    }
    print(f"{colors.get(color, colors['green'])}{text}{colors['end']}")

def run_command(command, shell=True, capture_output=False, check=False, detached=False):
    """Executa um comando no shell, com opções para rodar em segundo plano ou esperar."""
    print_color(f"\n> Executando: {command}", "blue")
    
    # Para comandos que não rodam em segundo plano (blocking)
    if not detached:
        process = subprocess.Popen(command, shell=shell, text=True, stdout=sys.stdout, stderr=sys.stderr)
        process.wait() # Espera o processo terminar
        if check and process.returncode != 0:
            print_color(f"Erro ao executar o comando: {command}", "red")
            sys.exit(1)
        return process

    # Para comandos em segundo plano (detached)
    result = subprocess.run(command, shell=shell, capture_output=capture_output, text=True, encoding='utf-8')
    if check and result.returncode != 0:
        print_color(f"Erro ao executar o comando: {command}", "red")
        print_color(result.stderr, "red")
        sys.exit(1)
    return result


def check_docker_running():
    # (Função original sem alterações)
    print_color("Verificando se o Docker está em execução...", "yellow")
    try:
        subprocess.run("docker info", shell=True, check=True, capture_output=True)
        print_color("Docker está ativo e pronto.", "green")
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        print_color("ERRO: Docker Desktop não parece estar em execução.", "red")
        print_color("Por favor, inicie o Docker Desktop e tente novamente.", "red")
        sys.exit(1)

def check_env_file():
    # (Função original sem alterações)
    print_color("Verificando arquivo de configuração .env...", "yellow")
    if not os.path.exists(ENV_FILE):
        print_color(f"Arquivo .env não encontrado. Copiando de {ENV_EXAMPLE_FILE}...", "yellow")
        if not os.path.exists(ENV_EXAMPLE_FILE):
             print_color(f"ERRO: {ENV_EXAMPLE_FILE} também não encontrado. Não é possível criar o .env.", "red")
             sys.exit(1)
        shutil.copy(ENV_EXAMPLE_FILE, ENV_FILE)
        print_color("IMPORTANTE: Abra o arquivo .env e preencha suas chaves de API e configurações de portfólio.", "red")
        sys.exit(1)
    print_color("Arquivo .env encontrado.", "green")
    
def check_env_configuration(mode_to_run):
    # (Função original sem alterações)
    print_color("Validando a configuração do ambiente...", "yellow")
    load_dotenv(dotenv_path=ENV_FILE)
    is_offline = os.getenv("FORCE_OFFLINE_MODE", "False").lower() == 'true'

    if is_offline and mode_to_run in ['test', 'trade']:
        print_color("="*60, "red")
        print_color("ERRO DE CONFIGURAÇÃO", "red")
        print_color(f"Você está tentando rodar em modo '{mode_to_run.upper()}' com 'FORCE_OFFLINE_MODE=True'.", "red")
        print_color("Um bot de trading não pode operar sem conexão com a internet.", "red")
        print_color("Ação: Mude 'FORCE_OFFLINE_MODE' para 'False' no arquivo .env ou use o modo 'optimize'.", "red")
        print_color("="*60, "red")
        sys.exit(1)
    print_color("Configuração do ambiente é válida.", "green")

def check_data_files():
    # (Função original sem alterações)
    print_color("Verificando arquivos de dados necessários...", "yellow")
    os.makedirs("data", exist_ok=True)
    if not os.path.exists(KAGGLE_DATA_FILE):
        print_color(f"ERRO: Arquivo de dados do Kaggle não encontrado em: {KAGGLE_DATA_FILE}", "red")
        print_color("Por favor, baixe o arquivo de dados (kaggle_btc_1m_bootstrap.csv) e coloque-o na pasta 'data'.", "red")
        sys.exit(1)
    print_color("Arquivo de dados do Kaggle encontrado.", "green")

def initial_setup():
    # (Função original sem alterações)
    print_color("--- Iniciando Setup e Verificação do Ambiente ---", "blue")
    check_env_file()
    check_data_files()
    run_command(f"\"{sys.executable}\" -m pip install -r requirements.txt", check=True)
    print_color("--- Setup Concluído com Sucesso ---", "green")

def docker_build():
    # (Função original sem alterações)
    check_docker_running()
    print_color(f"--- Construindo Imagem Docker: {DOCKER_IMAGE_NAME} ---", "blue")
    run_command(f"docker build -t {DOCKER_IMAGE_NAME} .", check=True)
    print_color("--- Imagem Docker Construída com Sucesso ---", "green")

# <<< PASSO 2: Criar a função Guardiã >>>
def model_guardian():
    """
    Verifica a validade do modelo atual. Se estiver expirado ou ausente,
    força uma nova otimização antes de continuar.
    """
    print_color("\n--- 🛡️ Guardião do Modelo: Verificando Status 🛡️ ---", "blue")
    
    if not os.path.exists(MODEL_METADATA_FILE):
        print_color("AVISO: Nenhum metadado de modelo encontrado.", "yellow")
        print_color("É necessário executar uma otimização inicial antes de operar.", "yellow")
        run_optimization_blocking()
        return

    try:
        with open(MODEL_METADATA_FILE, 'r') as f:
            metadata = json.load(f)
        
        valid_until_str = metadata.get("valid_until")
        if not valid_until_str:
            raise ValueError("Arquivo de metadados inválido, sem 'valid_until'.")
            
        valid_until = isoparse(valid_until_str)
        now_utc = datetime.now(timezone.utc)
        
        if now_utc > valid_until:
            print_color(f"AVISO: O modelo atual expirou em {valid_until.strftime('%Y-%m-%d')}.", "red")
            print_color("Iniciando um novo ciclo de otimização para garantir a performance...", "yellow")
            run_optimization_blocking()
        else:
            remaining_time = valid_until - now_utc
            print_color(f"✅ Modelo está válido. Expira em: {remaining_time.days} dias.", "green")

    except (FileNotFoundError, json.JSONDecodeError, ValueError) as e:
        print_color(f"Erro ao ler os metadados do modelo: {e}", "red")
        print_color("Recomendado executar uma nova otimização.", "yellow")
        run_optimization_blocking()

def run_optimization_blocking():
    """
    Executa o processo de otimização de forma que o script espere sua conclusão.
    """
    check_docker_running()
    check_env_configuration("optimize")
    
    container_name = "gcsbot-optimize-blocking"
    print_color(f"--- Iniciando Otimização (Modo de Espera) no container '{container_name}' ---", "blue")
    print_color("Este processo pode levar várias horas. O terminal ficará ocupado.", "yellow")
    
    data_volume = f"-v \"{os.path.abspath('data')}:/app/data\""
    logs_volume = f"-v \"{os.path.abspath('logs')}:/app/logs\""
    
    # Usa --rm -it para rodar em primeiro plano e remover o container ao final
    command = (f"docker run --rm -it --name {container_name} --env-file .env -e MODE=optimize {data_volume} {logs_volume} {DOCKER_IMAGE_NAME}")
    
    run_command(command, check=True, detached=False)
    print_color("--- Otimização Concluída ---", "green")


def start_bot(mode):
    """Inicia o bot usando Docker no modo especificado."""
    check_docker_running()
    check_env_configuration(mode)
    
    # Argumentos específicos de cada modo
    if mode in ['test', 'trade']:
        run_params = "-d --restart always"
        container_name = f"gcsbot-{mode}"
    elif mode == 'backtest':
        # Argumentos do backtest são passados diretamente da linha de comando
        args = " ".join(sys.argv[2:])
        run_params = f"--rm -it {args}"
        container_name = "gcsbot-backtest"
    else:
        print_color(f"Modo '{mode}' desconhecido para start_bot.", "red")
        return

    print_color(f"--- Iniciando Bot em Modo '{mode.upper()}' no container '{container_name}' ---", "blue")
    os.makedirs("data", exist_ok=True)
    os.makedirs("logs", exist_ok=True)
    
    data_volume = f"-v \"{os.path.abspath('data')}:/app/data\""
    logs_volume = f"-v \"{os.path.abspath('logs')}:/app/logs\""
    
    print_color(f"Removendo container antigo '{container_name}' se existir...", "yellow")
    run_command(f"docker rm -f {container_name}", capture_output=True, detached=True)

    command = (f"docker run {run_params} --name {container_name} --env-file .env -e MODE={mode} {data_volume} {logs_volume} {DOCKER_IMAGE_NAME}")
    
    run_command(command, check=True, detached=(mode in ['test', 'trade']))
    
    if mode in ['test', 'trade']:
        print_color(f"Bot no modo '{mode}' iniciado em segundo plano. Para ver os logs, use:", "green")
        print_color(f"python run.py logs", "blue")

def stop_bot():
    # (Função original sem alterações)
    check_docker_running()
    print_color("--- Parando e Removendo Containers do Bot ---", "yellow")
    result = run_command("docker ps -a --filter \"name=gcsbot-\" --format \"{{.Names}}\"", capture_output=True, detached=True)
    containers = [c for c in result.stdout.strip().split('\n') if c]
    
    if not containers:
        print_color("Nenhum container do bot encontrado para parar.", "green")
        return

    for container in containers:
        print_color(f"Parando o container {container}...")
        run_command(f"docker stop {container}", capture_output=True, detached=True)
        print_color(f"Removendo o container {container}...")
        run_command(f"docker rm {container}", capture_output=True, detached=True)
    
    print_color("Containers parados e removidos com sucesso.", "green")

def show_logs():
    # (Função original sem alterações)
    check_docker_running()
    print_color("--- Procurando por containers do bot ativos ---", "yellow")
    modes_to_check = ["test", "trade"] # Otimização agora roda em primeiro plano

    for mode in modes_to_check:
        container_name = f"gcsbot-{mode}"
        result = run_command(f"docker ps -q --filter \"name={container_name}\"", capture_output=True, detached=True)
        
        if result.stdout.strip():
            print_color(f"Anexando aos logs do container '{container_name}'. Pressione CTRL+C para sair.", "green")
            try:
                subprocess.run(f"docker logs -f {container_name}", shell=True)
            except KeyboardInterrupt:
                print_color("\n\nDesanexado dos logs.", "yellow")
            except subprocess.CalledProcessError:
                 print_color(f"\nO container '{container_name}' parou de executar.", "yellow")
            return

    print_color("Nenhum container do bot (gcsbot-test ou gcsbot-trade) está em execução.", "red")

# <<< PASSO 3: Adicionar o novo comando 'status' e integrar o guardião >>>
def show_status():
    """Apenas verifica e reporta o status de validade do modelo."""
    print_color("\n--- 🔍 Verificando Status do Modelo 🔍 ---", "blue")
    
    if not os.path.exists(MODEL_METADATA_FILE):
        print_color("Status: NENHUM MODELO ENCONTRADO.", "red")
        print_color("Execute 'python run.py optimize' para criar o primeiro modelo.", "yellow")
        return

    try:
        with open(MODEL_METADATA_FILE, 'r') as f:
            metadata = json.load(f)
        
        valid_until_str = metadata.get("valid_until")
        last_opt_str = metadata.get("last_optimization_date")
        
        valid_until = isoparse(valid_until_str)
        last_opt = isoparse(last_opt_str)
        now_utc = datetime.now(timezone.utc)
        
        if now_utc > valid_until:
            print_color("Status: EXPIRADO", "red")
        else:
            print_color("Status: VÁLIDO", "green")
            
        print(f"  - Última Otimização: {last_opt.strftime('%Y-%m-%d %H:%M')}")
        print(f"  - Válido Até:          {valid_until.strftime('%Y-%m-%d %H:%M')}")

    except Exception as e:
        print_color(f"Status: ERRO AO LER METADADOS ({e})", "red")

def main():
    if len(sys.argv) < 2:
        print_color("Uso: python run.py [comando]", "blue")
        print("Comandos disponíveis:")
        print("  setup      - Instala dependências e verifica o ambiente.")
        print("  build      - Constrói a imagem Docker do bot.")
        print("  optimize   - Roda a otimização para criar um novo modelo.")
        print("  backtest   - Roda um backtest rápido com o modelo atual.")
        print("  test       - Roda o bot em modo TEST (verifica validade do modelo antes).")
        print("  trade      - Roda o bot em modo TRADE (verifica validade do modelo antes).")
        print("  status     - Verifica a data de validade do modelo atual.")
        print("  stop       - Para e remove todos os containers do bot.")
        print("  logs       - Mostra os logs do bot que está rodando (test/trade).")
        return

    command = sys.argv[1].lower()
    
    if command == "setup": initial_setup()
    elif command == "build": docker_build()
    elif command == "optimize": run_optimization_blocking() # Agora chama a função de espera
    elif command == "status": show_status()
    elif command in ["backtest", "test", "trade"]:
        # <<< PASSO 4: O Guardião entra em ação aqui! >>>
        model_guardian()
        print_color(f"Guardião liberou a execução. Iniciando modo '{command}'...", "green")
        start_bot(command)
    elif command == "stop": stop_bot()
    elif command == "logs": show_logs()
    else: print_color(f"Comando '{command}' não reconhecido.", "red")

if __name__ == "__main__":
    main()