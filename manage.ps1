# manage.ps1 - Gestor de Comandos NATIVO para PowerShell

param (
    [string]$command
)

# Define cores para o output
$Yellow = [char]0x1b + "[93m"
$Green = [char]0x1b + "[92m"
$Reset = [char]0x1b + "[0m"

# --- BLOCO PARA SILENCIAR AVISOS ---
# Suprime os avisos do scikit-learn e lightgbm para um output mais limpo nos scripts
$env:PYTHONWARNINGS="ignore:::sklearn.exceptions.UserWarning,ignore:.*bagging_fraction is set.*:UserWarning,ignore:.*feature_fraction is set.*:UserWarning,ignore:.*lambda_l1 is set.*:UserWarning,ignore:.*lambda_l2 is set.*:UserWarning,ignore:.*bagging_freq is set.*:UserWarning"


switch ($command) {
    "setup" {
        Write-Host "${Yellow}--- Instalando dependências ---${Reset}"
        python -m pip install -r requirements.txt
        Write-Host ""
        Write-Host "${Yellow}--- Iniciando serviços ---${Reset}"
        python scripts/services.py start
        Write-Host ""
        Write-Host "${Green}--- Ambiente pronto! ---${Reset}"
    }
    "start-services" {
        Write-Host "${Yellow}--- Iniciando serviços ---${Reset}"
        python scripts/services.py start
    }
    "stop-services" {
        Write-Host "${Yellow}--- Parando serviços ---${Reset}"
        python scripts/services.py stop
    }
    "update-reqs" {
        Write-Host "${Yellow}--- Atualizando requirements.txt ---${Reset}"
        python -m pip freeze > requirements.txt
    }
    "optimize" {
        Write-Host "${Yellow}--- Iniciando a Fábrica de IAs (Otimizador) ---${Reset}"
        python src/core/optimizer.py
    }
    "backtest" {
         Write-Host "${Yellow}--- Iniciando o Laboratório de Simulação (Backtester) ---${Reset}"
         python run_backtest.py
    }
    default {
        Write-Host "${Yellow}GCS-Bot - Menu de Comandos${Reset}"
        Write-Host "---------------------------"
        Write-Host ""
        Write-Host "  ${Green}setup${Reset}          - Instala dependências e inicia os serviços."
        Write-Host "  ${Green}start-services${Reset} - Apenas inicia os serviços (Docker)."
        Write-Host "  ${Green}stop-services${Reset}  - Para os serviços (Docker)."
        Write-Host "  ${Green}update-reqs${Reset}    - Atualiza o ficheiro requirements.txt."
        Write-Host "  ${Green}optimize${Reset}       - Executa a otimização para treinar os modelos."
        Write-Host "  ${Green}backtest${Reset}       - Executa um backtest com os modelos treinados."
    }
}