GCS-Bot - Guia de Setup Rápido

Este guia contém os passos essenciais para configurar e executar o ambiente de desenvolvimento do GCS-Bot num novo computador com Windows.

Pré-requisitos
Antes de começar, garanta que tem o seguinte software instalado:

- Python (versão 3.10 ou superior)
- Git
- Docker Desktop (garanta que está em execução antes de começar o setup)
- Microsoft C++ Build Tools:
  - Abra o "Visual Studio Installer".
  - Vá a "Cargas de Trabalho" e instale "Desenvolvimento para desktop com C++".

1. Clonar o Repositório
   Abra o terminal e clone o projeto para a sua máquina:

git clone <URL_DO_SEU_REPOSITORIO>
cd gcsBot-btc

2. Configuração Inicial (Apenas na Primeira Vez)
   Execute os seguintes passos no terminal, a partir da pasta raiz do projeto.

Passo 2.1: Permitir Scripts PowerShell
Por segurança, o Windows bloqueia a execução de scripts. Execute este comando uma única vez para permitir que o seu utilizador corra scripts locais.

Abra o PowerShell como Administrador e execute:

Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned

Pressione S para confirmar e pode fechar o terminal de Administrador.

Passo 2.2: Criar e Ativar o Ambiente Virtual
Isto cria um ambiente Python isolado para o projeto, chamado .venv.

# Criar o ambiente virtual

python -m venv .venv

# Ativar o ambiente virtual (essencial para todos os passos seguintes)

.\.venv\Scripts\Activate.ps1

O seu terminal deverá agora mostrar (.venv) no início do prompt.

Passo 2.3: Criar Ficheiros de Configuração
Precisa de criar dois ficheiros de configuração na raiz do projeto, conforme os modelos abaixo.

Ficheiro de Segredos (.env):

# Segredos da Binance (modo REAL)

BINANCE_API_KEY="SUA_API_KEY_REAL_AQUI"
BINANCE_API_SECRET="SUA_SECRET_KEY_REAL_AQUI"

# Segredos da Binance (modo TESTNET - opcional mas recomendado)

BINANCE_TESTNET_API_KEY="SUA_API_KEY_TESTNET_AQUI"
BINANCE_TESTNET_API_SECRET="SUA_SECRET_KEY_TESTNET_AQUI"

# Credenciais do InfluxDB

INFLUXDB_URL="http://localhost:8086"
INFLUXDB_TOKEN="SEU_TOKEN_DO_INFLUXDB_AQUI"
INFLUXDB_ORG="NOME_DA_SUA_ORGANIZACAO_INFLUXDB"
INFLUXDB_BUCKET="btc_data"

Ficheiro de Parâmetros (config.yml):

app:
environment: "development"
use_testnet: false # Mude para 'true' se quiser usar a Testnet
force_offline_mode: false
data_paths:
data_dir: "data"
logs_dir: "logs"
model_metadata_file: "data/model_metadata.json"
historical_data_file: "data/btc_historical_data.csv"
kaggle_bootstrap_file: "data/kaggle_bootstrap.csv"

# ... (resto das configurações)

3. Comandos Principais com manage.ps1
   Com o ambiente virtual (.venv) ativo, todas as operações são feitas através do nosso gestor de comandos manage.ps1.

Setup Completo do Ambiente
Para instalar dependências e iniciar os serviços (InfluxDB), use o comando setup.

.\manage.ps1 setup

Na primeira vez que executa, isto irá configurar o InfluxDB. Abra http://localhost:8086 no seu navegador para completar o setup inicial (criar utilizador, senha, organização e o token).

Otimizar os Modelos (A Fábrica de IAs)
Execute o optimizer para treinar os especialistas da Mente-Colmeia. Este processo é longo e pode demorar várias horas.

.\manage.ps1 optimize

Executar um Backtest (O Simulador)
Após o otimizador ter criado pelo menos um modelo, execute o backtester para simular a performance.

.\manage.ps1 backtest

Outros Comandos Úteis

# Para ver todos os comandos disponíveis

.\manage.ps1

# Para apenas iniciar os serviços do Docker

.\manage.ps1 start-services

# Para parar os serviços do Docker

.\manage.ps1 stop-services

# Para atualizar o requirements.txt após instalar uma nova biblioteca

.\manage.ps1 update-reqs
