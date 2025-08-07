import subprocess
import os
import sys
import yaml

# --- Constantes ---
# Nome do serviço principal no docker-compose.yml
APP_SERVICE_NAME = "app"
# Nome do arquivo de override que será criado dinamicamente
OVERRIDE_FILE = "docker-compose.override.yml"
# Arquivos de status para os painéis de visualização
TRADING_STATUS_FILE = os.path.join("logs", "trading_status.json")
OPTIMIZER_STATUS_FILE = os.path.join("logs", "optimizer_status.json")


# --- Funções Auxiliares ---

def print_color(text, color="green"):
    """Imprime texto no terminal com cores."""
    colors = {
        "green": "\033[92m",
        "yellow": "\033[93m",
        "red": "\033[91m",
        "blue": "\033[94m",
        "end": "\033[0m",
    }
    print(f"{colors.get(color, colors['green'])}{text}{colors['end']}")


def run_command(command, capture_output=False, check=True):
    """
    Executa um comando no shell de forma segura e robusta.
    Trata interrupções (Ctrl+C) de forma graciosa.
    """
    display_command = ' '.join(command)
    print_color(f"\n> Executando: {display_command}", "blue")
    try:
        result = subprocess.run(
            command,
            capture_output=capture_output,
            text=True,
            check=check,
            encoding='utf-8'
        )
        return result
    except subprocess.CalledProcessError as e:
        print_color(f"ERRO ao executar o comando: {display_command}\n{e}", "red")
        sys.exit(1)
    except FileNotFoundError:
        print_color(f"ERRO: Comando '{command[0]}' não encontrado. Verifique se o Docker e o Docker Compose estão instalados e no PATH.", "red")
        sys.exit(1)
    except KeyboardInterrupt:
        print_color(f"\nComando '{display_command}' interrompido pelo usuário.", "yellow")
        sys.exit(1)


def check_docker_running():
    """Verifica se o serviço Docker está ativo."""
    print_color("Verificando status do Docker...", "yellow")
    run_command(["docker", "info"], capture_output=True)
    print_color("Docker está em execução.", "green")


# --- Comandos Principais ---

def build_images():
    """Constrói as imagens Docker e remove as imagens antigas (dangling)."""
    check_docker_running()
    print_color("--- Construindo imagens Docker (pode levar um tempo)...", "yellow")
    run_command(["docker-compose", "build"])
    print_color("--- Removendo imagens antigas (<none>)...", "yellow")
    run_command(["docker", "image", "prune", "-f", "--filter", "dangling=true"])
    print_color("--- Build concluído. ---", "green")


def start_services():
    """Inicia os serviços Docker (como o banco de dados) em background."""
    check_docker_running()
    print_color("--- Iniciando serviços em background (db, etc.)...", "yellow")
    run_command(["docker-compose", "up", "-d"])
    print_color("--- Serviços iniciados. ---", "green")


def stop_services():
    """Para e remove os contêineres, redes e o arquivo de override."""
    check_docker_running()
    print_color("--- Parando serviços Docker...", "yellow")
    run_command(["docker-compose", "down"])
    if os.path.exists(OVERRIDE_FILE):
        os.remove(OVERRIDE_FILE)
        print_color(f"--- Arquivo de override '{OVERRIDE_FILE}' removido. ---", "green")
    print_color("--- Serviços parados. ---", "green")


def reset_db():
    """Para os serviços e remove os volumes de dados (reset total)."""
    check_docker_running()
    print_color("--- ATENÇÃO: PARANDO E RESETANDO O AMBIENTE DOCKER ---", "red")
    run_command(["docker-compose", "down", "-v"])
    if os.path.exists(OVERRIDE_FILE):
        os.remove(OVERRIDE_FILE)
        print_color(f"--- Arquivo de override '{OVERRIDE_FILE}' removido. ---", "green")
    print_color("--- Reset completo. Use 'start' para começar de novo. ---", "green")


def run_in_foreground(args):
    """
    Executa um comando dentro de um novo contêiner 'app' em PRIMEIRO PLANO.
    Ideal para tarefas com início e fim, como scripts e testes.
    """
    check_docker_running()
    # CORREÇÃO TEMPORÁRIA: Removido o flag --rm que causa erro em algumas versões/setups do Docker Compose.
    # O efeito colateral é que contêineres parados podem se acumular.
    command = ["docker-compose", "run", APP_SERVICE_NAME] + args
    run_command(command)


def run_in_background(mode):
    """
    Cria um override para o docker-compose definindo o BOT_MODE e inicia o serviço.
    """
    check_docker_running()
    
    # Cria a estrutura de dados para o arquivo yaml de override.
    # Apenas definimos a variável de ambiente.
    override_config = {
        'services': {
            APP_SERVICE_NAME: {
                'environment': {
                    'BOT_MODE': mode
                }
            }
        }
    }
    
    # Escreve o arquivo de override
    with open(OVERRIDE_FILE, 'w') as f:
        yaml.dump(override_config, f)
    
    mode_name = mode.upper()
    print_color(f"--- Configurando o bot para o modo {mode_name} (background)...", "yellow")
    
    # Inicia o serviço em modo detached, forçando a recriação do contêiner
    # para garantir que a nova variável de ambiente seja usada.
    run_command(["docker-compose", "up", "-d", "--force-recreate"])
    
    print_color(f"--- Bot em modo {mode_name} iniciado. Use 'python run.py logs' para ver a atividade.", "green")
    print_color(f"--- Para parar, use 'python run.py stop'. ---", "green")


def show_logs():
    """Mostra e acompanha os logs do contêiner 'app'."""
    check_docker_running()
    print_color("--- Mostrando logs. Pressione CTRL+C para sair. ---", "yellow")
    run_command(["docker-compose", "logs", "-f", APP_SERVICE_NAME])


def show_dashboard(status_file, dashboard_func, name):
    """Função genérica para exibir um painel de status."""
    result = run_command(["docker-compose", "ps", "-q", APP_SERVICE_NAME], capture_output=True)
    if not result.stdout.strip():
        print_color(f"O contêiner '{APP_SERVICE_NAME}' não está em execução.", "red")
        print_color(f"Inicie o bot com 'python run.py trade' (ou outro modo) antes de ver o painel.", "yellow")
        return

    print_color(f"Exibindo painel do {name}. Pressione CTRL+C para sair.", "green")
    try:
        while True:
            if os.path.exists(status_file):
                try:
                    with open(status_file, 'r') as f:
                        import json
                        status_data = json.load(f)
                    os.system('cls' if os.name == 'nt' else 'clear')
                    dashboard_func(status_data)
                except (json.JSONDecodeError, KeyError) as e:
                    print(f"Aguardando um arquivo de status válido... Erro: {e}")
            else:
                print(f"Aguardando o {name} iniciar e criar o arquivo de status...")
            import time
            time.sleep(2)
    except KeyboardInterrupt:
        print_color(f"\nPainel do {name} encerrado.", "yellow")
    except ImportError as e:
        print_color(f"Erro de importação: {e}. Verifique se as dependências estão instaladas.", "red")


def print_help():
    """Exibe a mensagem de ajuda com os comandos disponíveis."""
    print_color("GCS-Bot - Painel de Controle", "yellow")
    print("---------------------------------")
    print("\nUso: python3 run.py [comando]\n")
    print_color("Gerenciamento do Ambiente:", "blue")
    print("  build           - Constrói/reconstrói as imagens Docker. Execute este comando primeiro.")
    print("  start           - Inicia os serviços de background (ex: banco de dados).")
    print("  stop            - Para todos os serviços Docker em execução.")
    print("  reset-db        - PERIGO! Para tudo e apaga os dados do banco de dados.")
    
    print_color("\nExecução do Bot (em Segundo Plano):", "blue")
    print("  trade           - Inicia o bot em modo de trade real.")
    print("  backtest        - Inicia o bot em modo de backtesting.")
    print("  test            - Inicia o bot em modo de paper trading (teste).")
    
    print_color("\nOperações e Scripts (em Primeiro Plano):", "blue")
    print("  optimize        - Executa o processo de otimização de modelo.")
    print("  update-db       - Executa o pipeline para popular/atualizar o banco de dados.")
    print("  run-tests       - Executa a suíte de testes automatizados (pytest).")
    
    print_color("\nUtilitários do Banco de Dados:", "blue")
    print("  clean-master    - Limpa a tabela 'features_master_table'.")
    print("  reset-trades    - Limpa todos os registros de trades do banco de dados.")
    print("  reset-sentiment - Limpa todos os dados de sentimento do banco de dados.")

    print_color("\nMonitoramento e Análise:", "blue")
    print("  logs            - Mostra os logs em tempo real do bot em execução.")
    print("  show-trading    - Mostra o painel de status do bot de trading.")
    print("  show-optimizer  - Mostra o painel de status do otimizador.")
    print("  analyze         - Analisa os resultados da última execução de backtest.")
    print("  analyze-decision <modelo> \"<data>\" - Analisa a decisão de um modelo específico.")


def main():
    """Ponto de entrada principal da CLI."""
    if len(sys.argv) < 2 or sys.argv[1].lower() in ['--help', '-h', 'help']:
        print_help()
        return

    command = sys.argv[1].lower()
    args = sys.argv[2:]

    commands = {
        "build": build_images,
        "start": start_services,
        "stop": stop_services,
        "reset-db": reset_db,
        "logs": show_logs,
        # Comandos de execução do Bot (agora em background)
        "trade": lambda: run_in_background("trade"),
        "backtest": lambda: run_in_background("backtest"),
        "test": lambda: run_in_background("test"),
        # Scripts e operações (executados em primeiro plano)
        "optimize": lambda: run_in_foreground(["python", "scripts/run_optimizer.py"]),
        "update-db": lambda: run_in_foreground(["python", "scripts/data_pipeline.py"]),
        "run-tests": lambda: run_in_foreground(["pytest"]),
        # Utilitários de DB
        "clean-master": lambda: run_in_foreground(["python", "scripts/db_utils.py", "features_master_table"]),
        "reset-trades": lambda: run_in_foreground(["python", "scripts/db_utils.py", "trades"]),
        "reset-sentiment": lambda: run_in_foreground(["python", "scripts/db_utils.py", "sentiment_fear_and_greed"]),
        # Análise
        "analyze": lambda: run_in_foreground(["python", "scripts/analyze_results.py"]),
        "analyze-decision": lambda: run_in_foreground(["python", "scripts/analyze_decision.py"] + args),
        # Dashboards
        "show-trading": lambda: show_dashboard(
            TRADING_STATUS_FILE,
            __import__('jules_bot.ui.display_manager').ui.display_manager.display_trading_dashboard,
            "Bot de Trading"
        ),
        "show-optimizer": lambda: show_dashboard(
            OPTIMIZER_STATUS_FILE,
            __import__('jules_bot.ui.display_manager').ui.display_manager.display_optimization_dashboard,
            "Otimizador"
        ),
    }

    if command in commands:
        if command == "analyze-decision" and not args:
            print_color("ERRO: O comando 'analyze-decision' requer <modelo> e \"<data>\".", "red")
            return
        commands[command]()
    else:
        print_color(f"Comando '{command}' não reconhecido.", "red")
        print_help()


if __name__ == "__main__":
    main()
