import subprocess
import os
import sys
import shutil

# --- Configuração do Projeto ---
DOCKER_IMAGE_NAME = "gcsbot"
KAGGLE_DATA_FILE = os.path.join("data", "kaggle_btc_1m_bootstrap.csv")
ENV_FILE = ".env"
ENV_EXAMPLE_FILE = ".env.example"
# -----------------------------

def print_color(text, color="green"):
    """Imprime texto colorido no terminal."""
    colors = {
        "green": "\033[92m", "yellow": "\033[93m", "red": "\033[91m",
        "blue": "\033[94m", "end": "\033[0m",
    }
    print(f"{colors.get(color, colors['green'])}{text}{colors['end']}")

def run_command(command, shell=True, capture_output=False, check=False):
    """Executa um comando no shell e retorna o resultado, com opção de parar em caso de erro."""
    print_color(f"\n> Executando: {command}", "blue")
    # Usar 'utf-8' para evitar problemas de encoding em diferentes sistemas
    result = subprocess.run(command, shell=shell, capture_output=capture_output, text=True, encoding='utf-8')
    if check and result.returncode != 0:
        print_color(f"Erro ao executar o comando: {command}", "red")
        print_color(result.stderr, "red")
        sys.exit(1)
    return result

def check_docker_running():
    """Verifica se o Docker Desktop está em execução."""
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
    """Verifica se o arquivo .env existe e o cria a partir do exemplo se necessário."""
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

def check_data_files():
    """Verifica se os arquivos de dados essenciais existem."""
    print_color("Verificando arquivos de dados necessários...", "yellow")
    os.makedirs("data", exist_ok=True)
    if not os.path.exists(KAGGLE_DATA_FILE):
        print_color(f"ERRO: Arquivo de dados do Kaggle não encontrado em: {KAGGLE_DATA_FILE}", "red")
        print_color("Por favor, baixe o arquivo de dados (kaggle_btc_1m_bootstrap.csv) e coloque-o na pasta 'data'.", "red")
        sys.exit(1)
    print_color("Arquivo de dados do Kaggle encontrado.", "green")

def initial_setup():
    """Executa todas as verificações de inicialização."""
    print_color("--- Iniciando Setup e Verificação do Ambiente ---", "blue")
    check_env_file()
    check_data_files()
    run_command(f"\"{sys.executable}\" -m pip install -r requirements.txt", check=True)
    print_color("--- Setup Concluído com Sucesso ---", "green")

def docker_build():
    """Constrói a imagem Docker para o bot."""
    check_docker_running()
    print_color(f"--- Construindo Imagem Docker: {DOCKER_IMAGE_NAME} ---", "blue")
    run_command(f"docker build -t {DOCKER_IMAGE_NAME} .", check=True)
    print_color("--- Imagem Docker Construída com Sucesso ---", "green")

def start_bot(mode):
    """Inicia o bot usando Docker no modo especificado."""
    check_docker_running()
    container_name = f"gcsbot-{mode}"
    print_color(f"--- Iniciando Bot em Modo '{mode.upper()}' no container '{container_name}' ---", "blue")
    os.makedirs("data", exist_ok=True)
    os.makedirs("logs", exist_ok=True)
    
    # Prepara os caminhos dos volumes de forma compatível com múltiplos SO
    data_volume = f"-v \"{os.path.abspath('data')}:/app/data\""
    logs_volume = f"-v \"{os.path.abspath('logs')}:/app/logs\""
    
    # Define os parâmetros de execução com base no modo
    if mode in ['test', 'trade']:
        # Modos de serviço contínuo: rodam em segundo plano e reiniciam sempre
        run_params = "-d --restart always"
    elif mode == 'optimize':
        # Modo de tarefa: roda em segundo plano, mas não reinicia automaticamente.
        # O --rm é removido para que possamos ver os logs depois.
        run_params = "-d" 
    else:
        # Modo padrão para qualquer outro comando (se houver): roda em primeiro plano e remove ao sair
        run_params = "--rm"

    # Garante que não haja um container antigo com o mesmo nome
    print_color(f"Removendo container antigo '{container_name}' se existir...", "yellow")
    run_command(f"docker rm -f {container_name}", capture_output=True)

    command = (f"docker run {run_params} --name {container_name} --env-file .env -e MODE={mode} {data_volume} {logs_volume} {DOCKER_IMAGE_NAME}")
    
    run_command(command, check=True)
    
    # Mensagem de sucesso unificada para todos os modos que rodam em segundo plano
    if mode in ['test', 'trade', 'optimize']:
        print_color(f"Bot no modo '{mode}' iniciado em segundo plano. Para ver os logs, use:", "green")
        print_color(f"python run.py logs", "blue")
    else:
        print_color("Processo iniciado. Você pode acompanhar o progresso nesta janela.", "yellow")

def stop_bot():
    """Para e remove todos os containers do bot (funciona no Windows, Linux e macOS)."""
    check_docker_running()
    print_color("--- Parando e Removendo Containers do Bot ---", "yellow")
    result = run_command("docker ps -a --filter \"name=gcsbot-\" --format \"{{.Names}}\"", capture_output=True)
    containers = [c for c in result.stdout.strip().split('\n') if c]
    
    if not containers:
        print_color("Nenhum container do bot encontrado para parar.", "green")
        return

    for container in containers:
        print_color(f"Parando o container {container}...")
        run_command(f"docker stop {container}", capture_output=True)
        print_color(f"Removendo o container {container}...")
        run_command(f"docker rm {container}", capture_output=True)
    
    print_color("Containers parados e removidos com sucesso.", "green")

def show_logs():
    """Mostra os logs de um container do bot que estiver ativo (test, trade ou optimize)."""
    check_docker_running()
    print_color("--- Procurando por containers do bot ativos ---", "yellow")

    # Lista de modos para procurar, em ordem de prioridade
    modes_to_check = ["optimize", "test", "trade"]

    for mode in modes_to_check:
        container_name = f"gcsbot-{mode}"
        # Verifica se o container com esse nome está em execução
        result = run_command(f"docker ps -q --filter \"name={container_name}\"", capture_output=True)
        
        if result.stdout.strip():
            print_color(f"Anexando aos logs do container '{container_name}'. Pressione CTRL+C para sair.", "green")
            try:
                # Usa subprocess.run para que o CTRL+C seja capturado corretamente
                subprocess.run(f"docker logs -f {container_name}", shell=True)
            except KeyboardInterrupt:
                print_color("\n\nDesanexado dos logs.", "yellow")
            except subprocess.CalledProcessError:
                 # Ocorre se o container parar enquanto os logs estão sendo vistos
                 print_color(f"\nO container '{container_name}' parou de executar.", "yellow")
            return # Sai da função após encontrar e mostrar os logs

    print_color("Nenhum container do bot (gcsbot-optimize, gcsbot-test ou gcsbot-trade) está em execução.", "red")

def main():
    if len(sys.argv) < 2:
        print_color("Uso: python run.py [comando]", "blue")
        print("Comandos disponíveis:")
        print("  setup      - Instala dependências e verifica o ambiente.")
        print("  build      - Constrói a imagem Docker do bot.")
        print("  optimize   - Roda a otimização em segundo plano via Docker.")
        print("  test       - Roda o bot em modo TEST na Testnet 24/7 via Docker.")
        print("  trade      - Roda o bot em modo TRADE na conta real 24/7 via Docker.")
        print("  stop       - Para e remove todos os containers do bot.")
        print("  logs       - Mostra os logs do bot que está rodando (optimize/test/trade).")
        return

    command = sys.argv[1].lower()
    
    if command == "setup": initial_setup()
    elif command == "build": docker_build()
    elif command == "optimize": start_bot("optimize")
    elif command == "test": start_bot("test")
    elif command == "trade": start_bot("trade")
    elif command == "stop": stop_bot()
    elif command == "logs": show_logs()
    else: print_color(f"Comando '{command}' não reconhecido.", "red")

if __name__ == "__main__":
    main()