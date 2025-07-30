# manage.ps1 - Gestor de Comandos Profissional para PowerShell

param (
    [string]$command
)

# Define cores para o output
$Yellow = [char]0x1b + "[93m"
$Green = [char]0x1b + "[92m"
$Red = [char]0x1b + "[91m"
$Reset = [char]0x1b + "[0m"

# Suprime os avisos do scikit-learn para um output mais limpo
$env:PYTHONWARNINGS="ignore:::sklearn.exceptions.UserWarning"

switch ($command) {
    "setup" {
        Write-Host "${Yellow}--- Construindo as imagens Docker (pode demorar na primeira vez)...${Reset}"
        docker-compose build
        Write-Host "${Yellow}--- Iniciando serviços em segundo plano...${Reset}"
        docker-compose up -d
        Write-Host "${Green}--- Ambiente pronto! Use '.\manage.ps1 optimize' para começar. ---${Reset}"
    }
    "start-services" {
        Write-Host "${Yellow}--- Iniciando serviços (Docker)...${Reset}"
        docker-compose up -d
    }
    "stop-services" {
        Write-Host "${Yellow}--- Parando serviços (Docker)...${Reset}"
        docker-compose down
    }
    "reset-db" {
        Write-Host "${Yellow}--- PARANDO E RESETANDO O AMBIENTE DOCKER ---${Reset}"
        docker-compose down
        Write-Host "${Yellow}--- REMOVENDO VOLUME DE DADOS ANTIGO DO INFLUXDB ---${Reset}"
        # O nome do volume é <nome_da_pasta_do_projeto>_influxdb_data
        docker volume rm gcsbot-btc_influxdb_data
        Write-Host "${Green}--- Reset concluído. Use 'start-services' para começar de novo. ---${Reset}"
    }
    "optimize" {
        Write-Host "${Yellow}--- Iniciando a Fábrica de IAs (Otimizador) DENTRO do container...${Reset}"
        docker-compose exec app python src/core/optimizer.py
    }
    "backtest" {
         Write-Host "${Yellow}--- Iniciando o Laboratório de Simulação (Backtester) DENTRO do container...${Reset}"
         docker-compose exec app python run_backtest.py
    }
    "update-db" {
        Write-Host "${Yellow}--- Iniciando Pipeline de Ingestão de Dados (ETL)...${Reset}"
        docker-compose exec app python scripts/data_pipeline.py
    }
    default {
        Write-Host "${Yellow}GCS-Bot - Painel de Controle${Reset}"
        Write-Host "---------------------------"
        Write-Host ""
        Write-Host " Gestão do Ambiente:"
        Write-Host "  ${Green}setup${Reset}           - Configura o ambiente Docker completo pela primeira vez."
        Write-Host "  ${Green}start-services${Reset}  - Inicia os containers Docker (app, db)."
        Write-Host "  ${Green}stop-services${Reset}   - Para os containers Docker."
        Write-Host "  ${Red}reset-db${Reset}        - PARA e APAGA o banco de dados. Começa do zero."
        Write-Host ""
        Write-Host " Operações do Bot:"
        Write-Host "  ${Green}optimize${Reset}        - Executa a otimização para treinar os modelos."
        Write-Host "  ${Green}backtest${Reset}        - Executa um backtest com os modelos treinados."
        Write-Host "  ${Green}update-db${Reset}       - Executa o pipeline ETL completo para popular e atualizar o DB."
    }
}