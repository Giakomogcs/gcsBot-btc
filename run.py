import os
import sys
import shutil
import typer
import subprocess
from typing import Optional

# Adiciona o caminho do projeto para permitir importações locais
# Supondo que este script esteja em um subdiretório como 'cli/'
# sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# --- Importações da sua aplicação (substitua pelos seus caminhos reais se necessário) ---
# Como não tenho os arquivos, estou usando placeholders. 
# Descomente e ajuste os imports conforme a estrutura do seu projeto.
# from jules_bot.config import GCSBotConfig
# from jules_bot.backtesting.engine import Backtester
# from jules_bot.database.database_manager import DatabaseManager
# from jules_bot.ui.display_manager import JulesBotApp
# from collectors.core_price_collector import prepare_backtest_data

# --- Placeholders para as classes (remova ao usar seus imports reais) ---
class GCSBotConfig:
    def get(self, key):
        print(f"DEBUG: Obtendo configuração para '{key}'")
        if key == 'backtest.default_lookback_days':
            return 30
        if key == 'influxdb_connection':
            return {'url': 'http://localhost:8086', 'token': 'token-secreto', 'org': 'gcsbot_org'}
        if key == 'influxdb_trade':
            return {'bucket': 'live_trades'}
        if key == 'influxdb_backtest':
            return {'bucket': 'backtest_results'}
        return {}

class DatabaseManager:
    def __init__(self, config):
        print(f"DEBUG: DatabaseManager inicializado com config: {config}")

class JulesBotApp:
    def __init__(self, db_manager, display_mode):
        self.db_manager = db_manager
        self.display_mode = display_mode
        print(f"DEBUG: JulesBotApp UI inicializada no modo '{display_mode}'")
    def run(self):
        print(f"--- UI rodando no modo {self.display_mode} ---")
        print("Pressione Ctrl+C para sair.")
        try:
            while True:
                pass
        except KeyboardInterrupt:
            print("\nUI encerrada.")

class Backtester:
    def __init__(self, days):
        self.days = days
        print(f"DEBUG: Backtester inicializado para {days} dias.")
    def run(self):
        print(f"--- Rodando backtest para {self.days} dias ---")
        # Simula um processo de backtest
        import time
        time.sleep(2)
        print("Backtest concluído.")

def prepare_backtest_data(days):
    print(f"DEBUG: Preparando dados de backtest para {days} dias.")
    # Simula o download e preparação de dados
    import time
    time.sleep(1)
    print("Dados preparados.")

# --- Fim dos Placeholders ---

app = typer.Typer()
config_manager = GCSBotConfig()

# --- Lógica de Detecção do Docker Compose ---

def get_docker_compose_command():
    """
    Verifica se 'docker-compose' (V1) ou 'docker compose' (V2) está disponível.
    
    Retorna:
        list: A lista de argumentos de comando base a ser usada (ex: ['docker-compose'] ou ['docker', 'compose']).
    
    Raises:
        FileNotFoundError: Se nem 'docker' nem 'docker-compose' forem encontrados no PATH do sistema.
    """
    if shutil.which("docker-compose"):
        return ["docker-compose"]
    elif shutil.which("docker"):
        # Verifica se 'compose' é um subcomando válido para evitar erros
        try:
            result = subprocess.run(["docker", "compose", "--version"], capture_output=True, text=True, check=True)
            if "Docker Compose version" in result.stdout:
                return ["docker", "compose"]
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass # Continua para o erro final se 'docker compose' não for válido
            
    raise FileNotFoundError("Could not find a valid 'docker-compose' or 'docker compose' command. Please ensure Docker is installed and in your PATH.")

# --- Comandos do Ambiente Docker ---

env_app = typer.Typer(help="Gerencia o ambiente Docker.")

@env_app.command("start")
def env_start():
    """Constrói e inicia todos os serviços em modo detached."""
    print("🚀 Iniciando serviços Docker...")
    try:
        command = get_docker_compose_command() + ["up", "--build", "-d"]
        print(f"   (usando comando: `{' '.join(command)}`)")
        subprocess.run(command, check=True, capture_output=True)
        print("✅ Serviços iniciados com sucesso.")
    except FileNotFoundError as e:
        print(f"❌ Erro: {e}")
    except subprocess.CalledProcessError as e:
        print(f"❌ Erro ao iniciar os serviços. Código de saída: {e.returncode}")
        print(f"   Stderr:\n{e.stderr.decode()}")

@env_app.command("stop")
def env_stop():
    """Para e remove todos os serviços."""
    print("🔥 Parando serviços Docker...")
    try:
        command = get_docker_compose_command() + ["down"]
        print(f"   (usando comando: `{' '.join(command)}`)")
        subprocess.run(command, check=True, capture_output=True)
        print("✅ Serviços parados com sucesso.")
    except FileNotFoundError as e:
        print(f"❌ Erro: {e}")
    except subprocess.CalledProcessError as e:
        print(f"❌ Erro ao parar os serviços. Código de saída: {e.returncode}")
        print(f"   Stderr:\n{e.stderr.decode()}")

@env_app.command("status")
def env_status():
    """Mostra o status de todos os serviços."""
    print("📊 Verificando status dos serviços Docker...")
    try:
        command = get_docker_compose_command() + ["ps"]
        print(f"   (usando comando: `{' '.join(command)}`)")
        subprocess.run(command, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"❌ Erro ao verificar status: {e}")

@env_app.command("logs")
def env_logs(service_name: Optional[str] = typer.Argument(None, help="Nome do serviço para ver os logs (ex: 'app', 'db').")):
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
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"❌ Erro ao obter logs: {e}")

@env_app.command("rebuild")
def env_rebuild():
    """Força a reconstrução das imagens Docker sem iniciá-las."""
    print("🛠️ Forçando reconstrução das imagens Docker...")
    try:
        command = get_docker_compose_command() + ["build", "--no-cache"]
        print(f"   (usando comando: `{' '.join(command)}`)")
        subprocess.run(command, check=True)
        print("✅ Imagens reconstruídas com sucesso.")
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"❌ Erro ao reconstruir imagens: {e}")

app.add_typer(env_app, name="env")

# --- Comandos de Atalho (Aliases) ---

@app.command("start")
def start():
    """Constrói e inicia todos os serviços em modo detached."""
    env_start()

@app.command("stop")
def stop():
    """Para e remove todos os serviços."""
    env_stop()

@app.command("build")
def build():
    """Força a reconstrução das imagens Docker sem iniciá-las."""
    env_rebuild()

@app.command("status")
def status():
    """Mostra o status de todos os serviços."""
    env_status()

@app.command("logs")
def logs(service_name: Optional[str] = typer.Argument(None, help="Nome do serviço para ver os logs.")):
    """Acompanha os logs de um serviço específico ou de todos."""
    env_logs(service_name)

# --- Comandos da Aplicação ---

@app.command()
def trade():
    """[NÃO IMPLEMENTADO] Inicia o bot em modo de negociação ao vivo."""
    print("O modo de negociação ao vivo ainda não foi implementado.")

@app.command()
def backtest(
    days: Optional[int] = typer.Option(
        None, "--days", "-d", help="Número de dias de dados recentes para buscar para o backtest."
    )
):
    """Executa um backtest completo usando os dados mais recentes do banco de dados."""
    print("🚀 Iniciando nova execução de backtest...")
    try:
        if days is None:
            days = int(config_manager.get('backtest.default_lookback_days'))
            print(f"Nenhum --days especificado. Usando o padrão de {days} dias do config.ini.")

        print(f"Preparando dados: buscando os últimos {days} dias de dados de mercado...")
        prepare_backtest_data(days=days)

        print("Preparação de dados concluída. Iniciando o motor de backtesting...")
        backtester = Backtester(days=days)
        backtester.run()
        print("✅ Backtest finalizado com sucesso.")

    except Exception as e:
        print(f"❌ Ocorreu um erro durante o backtest: {e}")
        import traceback
        traceback.print_exc()

@app.command()
def show(
    mode: str = typer.Argument("trade", help="O modo a ser exibido: 'trade' ou 'backtest'")
):
    """Inicia a UI do Terminal para exibir o estado de um bot ou os resultados do backtest."""
    if mode not in ['trade', 'backtest']:
        print(f"❌ Erro: Modo inválido '{mode}'. Use 'trade' ou 'backtest'.")
        raise typer.Exit()

    print(f"🚀 Lançando UI no modo '{mode}'...")
    
    try:
        db_config_name = f"influxdb_{mode}"
        db_config = config_manager.get(db_config_name)
        
        full_db_config = {
            **config_manager.get('influxdb_connection'),
            **db_config
        }
        
        db_manager = DatabaseManager(config=full_db_config)
        app_ui = JulesBotApp(db_manager=db_manager, display_mode=mode)
        app_ui.run()

    except Exception as e:
        print(f"❌ Erro ao lançar a UI: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    app()
