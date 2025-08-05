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
        docker-compose exec app python scripts/run_optimizer.py
    }
    "backtest" {
         Write-Host "${Yellow}--- Iniciando o Laboratório de Simulação (Backtester) DENTRO do container...${Reset}"
         docker-compose exec app python scripts/run_backtest.py
    }
    "update-db" {
        Write-Host "${Yellow}--- Iniciando Pipeline de Ingestão de Dados (ETL)...${Reset}"
        docker-compose exec app python scripts/data_pipeline.py
    }
    "clean-master" {
        Write-Host "${Yellow}--- Limpando a 'features_master_table' antiga...${Reset}"
        docker-compose exec app python scripts/db_utils.py features_master_table
        Write-Host "${Yellow}--- Tabela limpa. Executando 'update-db' para recriar com o novo schema...${Reset}"
        # Chama a lógica do comando 'update-db'
        docker-compose exec app python scripts/data_pipeline.py
    }
    "reset-trades" {
        Write-Host "${Yellow}--- Apagando todos os registos de trades da base de dados...${Reset}"
        docker-compose exec app python scripts/db_utils.py trades
        Write-Host "${Green}--- Histórico de trades limpo. Pode executar o bot novamente. ---${Reset}"
    }
    "reset-sentiment" {
        Write-Host "${Yellow}--- Apagando dados de Sentimento (Fear & Greed)...${Reset}"
        docker-compose exec app python scripts/db_utils.py sentiment_fear_and_greed
        Write-Host "${Green}--- Histórico de Sentimento limpo. ---${Reset}"
    }
    "analyze" {
        Write-Host "${Cyan}--- Executando script de análise de resultados DENTRO do container...${Reset}"
        docker-compose exec app python scripts/analyze_results.py
    }
    "run-live" {
        Write-Host "${Green}--- 🚀 INICIANDO O BOT EM MODO DE OPERAÇÃO (LOOP PRINCIPAL) 🚀 ---${Reset}"
        Write-Host "${Yellow}Use Ctrl+C para parar o bot.${Reset}"
        docker-compose exec app python main.py
    }
    "analyze-decision" {
        # $args é uma variável automática que contém todos os outros argumentos
        if ($args.Count -ne 2) {
            Write-Host "${Red}Uso: .\manage.ps1 analyze-decision <nome_do_modelo> \"AAAA-MM-DD HH:MM:SS\"${Reset}"
            Write-Host "${Yellow}Exemplo: .\manage.ps1 analyze-decision price_action \"2024-08-01 10:30:00\"${Reset}"
            return
        }
        $model = $args[0]
        $datetime = $args[1]
        
        Write-Host "${Cyan}--- Analisando a decisão do modelo '$model' para o momento '$datetime'...${Reset}"
        docker-compose exec app python scripts/analyze_decision.py $model "$datetime"
    }
    "test" {
        Write-Host "${Yellow}--- Executando a suíte de testes (pytest) DENTRO do container...${Reset}"
        docker-compose exec app pytest
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
        Write-Host "  ${Red}clean-master${Reset}      - APAGA apenas a tabela Master, mantendo os dados das demais tabelas." 
        Write-Host "  ${Red}reset-trades${Reset}      - APAGA apenas o histórico de trades, mantendo os dados de mercado." 
        Write-Host "  ${Red}reset-sentiment${Reset}      - APAGA apenas o histórico de sentiment, mantendo os dados de mercado." 
        Write-Host "  ${Cyan}analyze-decision${Reset} - Analisa o 'porquê' de uma decisão de um modelo num ponto específico."
        Write-Host ""
        Write-Host " Operações do Bot:"
        Write-Host "  ${Green}optimize${Reset}        - Executa a otimização para treinar os modelos."
        Write-Host "  ${Green}backtest${Reset}        - Executa um backtest com os modelos treinados."
        Write-Host "  ${Green}update-db${Reset}       - Executa o pipeline ETL completo para popular e atualizar o DB."
        Write-Host "  ${Green}test${Reset}            - Executa a suíte de testes automatizados (pytest)."
        Write-Host "  ${Cyan}analyze${Reset}         - Analisa os resultados do último backtest."
        Write-Host "  ${Red}run-live${Reset}          - Inicia o bot para operação em tempo real/paper trading." # Adicionar esta linha na ajuda
    }
}