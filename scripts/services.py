# scripts/services.py
import subprocess
import sys

# --- Variáveis (ajuste se necessário) ---
DOCKER_INFLUXDB_CONTAINER_NAME = "influxdb"

def run_command(command):
    """Executa um comando no shell e lida com erros."""
    try:
        subprocess.run(command, check=True, shell=True)
    except subprocess.CalledProcessError as e:
        print(f"❌ Erro ao executar o comando: {' '.join(command)}\n{e}")
        sys.exit(1)
    except FileNotFoundError:
        print(f"❌ Comando não encontrado: {command[0]}. Verifique se o Docker está instalado e no PATH.")
        sys.exit(1)

def start_services():
    """Inicia os serviços de backend (ex: InfluxDB) via Docker."""
    print("Iniciando serviços de backend...")
    
    # Verifica se o docker está em execução
    try:
        subprocess.run("docker ps", check=True, capture_output=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("❌ Docker não parece estar em execução. Por favor, inicie o Docker Desktop e tente novamente.")
        return

    # Obtém o status do contêiner
    container_id_running = subprocess.run(
        f"docker ps -q -f name={DOCKER_INFLUXDB_CONTAINER_NAME}", 
        capture_output=True, text=True, shell=True
    ).stdout.strip()
    
    if container_id_running:
        print("✅ Contêiner InfluxDB já está em execução.")
        return

    container_id_exited = subprocess.run(
        f"docker ps -aq -f status=exited -f name={DOCKER_INFLUXDB_CONTAINER_NAME}", 
        capture_output=True, text=True, shell=True
    ).stdout.strip()

    if container_id_exited:
        print("Contêiner InfluxDB encontrado, mas parado. Iniciando...")
        run_command(f"docker start {DOCKER_INFLUXDB_CONTAINER_NAME}")
    else:
        print("Criando e iniciando novo contêiner InfluxDB...")
        run_command(f"docker run -d --name {DOCKER_INFLUXDB_CONTAINER_NAME} -p 8086:8086 influxdb:2.7")
    
    print("✅ Serviços iniciados com sucesso!")


def stop_services():
    """Para todos os serviços de backend que estão rodando."""
    print("Parando serviços de backend...")
    run_command(f"docker stop {DOCKER_INFLUXDB_CONTAINER_NAME}")
    print("✅ Serviços parados com sucesso!")


if __name__ == '__main__':
    command = sys.argv[1] if len(sys.argv) > 1 else None
    if command == "start":
        start_services()
    elif command == "stop":
        stop_services()
    else:
        print("Comando inválido. Use 'start' ou 'stop'.")