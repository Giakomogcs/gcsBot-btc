# Robô GCS-BTC

![Python Version](https://img.shields.io/badge/python-3.10%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Status](https://img.shields.io/badge/status-active-brightgreen)

## Índice

- [Descrição do Projeto](#descrição-do-projeto)
- [Pré-requisitos](#pré-requisitos)
- [Instalação e Configuração Inicial](#instalação-e-configuração-inicial)
- [Guia de Uso e Comandos](#guia-de-uso-e-comandos)
  - [Comandos de Gerenciamento do Ambiente](#comandos-de-gerenciamento-do-ambiente)
  - [Comandos de Gerenciamento de Bots](#comandos-de-gerenciamento-de-bots)
  - [Comandos de Execução e Monitoramento](#comandos-de-execução-e-monitoramento)
  - [Scripts de Utilidade](#scripts-de-utilidade)
- [Entendendo as Métricas de Performance](#entendendo-as-métricas-de-performance)
- [Estrutura do Projeto](#estrutura-do-projeto)
- [Como Contribuir](#como-contribuir)

## Descrição do Projeto

O **Robô de Automação Jules** é um sistema de trading automatizado, robusto e flexível, projetado para operar no mercado de criptomoedas da Binance. Sua arquitetura é centrada em Docker, permitindo que cada bot opere em um contêiner isolado, garantindo estabilidade e escalabilidade. O sistema é controlado por uma poderosa interface de linha de comando (`run.py`) que gerencia todo o ciclo de vida dos bots, desde a criação e configuração até a execução e monitoramento em tempo real.

## Pré-requisitos

Para executar este projeto, você precisará ter os seguintes softwares instalados em sua máquina:

- **Python 3.10 ou superior**
- **Docker**
- **Docker Compose** (geralmente incluído com o Docker Desktop)

## Instalação e Configuração Inicial

Siga este guia para configurar o ambiente de desenvolvimento do zero.

### Passo 1: Clonar o Repositório

```bash
git clone [URL_DO_REPOSITORIO]
cd [NOME_DA_PASTA_DO_PROJETO]
```

### Passo 2: Criar e Ativar o Ambiente Virtual (`venv`)

É altamente recomendado usar um ambiente virtual para isolar as dependências do projeto.

**Para Windows (PowerShell):**

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

**Para Linux/macOS (Bash):**

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### Passo 3: Instalar as Dependências

Com o ambiente virtual ativado, instale todas as bibliotecas Python necessárias:

```bash
pip install -r requirements.txt
```

### Passo 4: Configurar as Variáveis de Ambiente

O projeto utiliza um arquivo `.env` para gerenciar segredos e configurações.

1.  **Copie o arquivo de exemplo:**

    ```bash
    cp .env.example .env
    ```

2.  **Edite o arquivo `.env`** e preencha as variáveis de acordo com o guia detalhado abaixo.

## Guia Completo das Variáveis de Ambiente (.env)

Este guia detalha todas as variáveis de ambiente que podem ser configuradas no arquivo `.env`. A configuração correta é crucial para o funcionamento, a estratégia e a segurança do seu robô.

**Hierarquia de Configuração:** O sistema carrega as configurações na seguinte ordem de precedência (onde 1 é o mais alto):

1.  **Variáveis de Ambiente do Sistema:** Definidas diretamente no seu terminal ou contêiner Docker.
2.  **Arquivo `.env`:** Onde você define suas configurações personalizadas.
3.  **Arquivo `config.ini`:** Contém os valores padrão do sistema.

---

### Configurações do Núcleo do Bot (Core Bot Settings)

Estas variáveis controlam o comportamento fundamental e a identidade do bot.

| Variável                            | Descrição                                                                                                                                                                                                                                                                                                                                                                               | Valor Padrão |
| ----------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------ |
| `BOT_NAME`                          | O nome único do seu bot. Usado para prefixar logs, contêineres Docker e buscar variáveis de ambiente específicas (ex: `MEU_BOT_API_KEY`).                                                                                                                                                                                                                                               | `jules_bot`  |
| `BOT_MODE`                          | Define o modo de operação. `live` para negociações reais, `test` para paper trading na Testnet da Binance.                                                                                                                                                                                                                                                                              | `test`       |
| `ENV_FILE`                          | O caminho para o arquivo de ambiente a ser carregado.                                                                                                                                                                                                                                                                                                                                   | `.env`       |
| `JULES_BOT_SCRIPT_MODE`             | Usado internamente para controlar o comportamento do script. `0` para modo normal.                                                                                                                                                                                                                                                                                                      | `0`          |
| `APP_SYMBOL`                        | O par de moedas que o robô irá negociar (ex: `BTCUSDT`, `ETHUSDT`).                                                                                                                                                                                                                                                                                                                     | `BTCUSDT`    |
| `APP_FORCE_OFFLINE_MODE`            | **`true`**: Força o bot a operar em modo offline, sem se conectar à exchange. Nenhuma transação real ou consulta de saldo será feita. Útil para depuração de lógica interna.<br>**`false`**: O bot se conectará à Binance (Live ou Testnet).                                                                                                                                            | `false`      |
| `APP_USE_TESTNET`                   | **`true`**: O bot se conectará à API da **Testnet** da Binance. Ele usará as chaves `BINANCE_TESTNET_API_KEY` e `BINANCE_TESTNET_API_SECRET`.<br>**`false`**: O bot se conectará à API de produção (**Live**) da Binance. Ele usará as chaves `BINANCE_API_KEY` e `BINANCE_API_SECRET`.<br>_Nota: Esta variável é frequentemente controlada pelo comando `run.py` (`trade` ou `test`)._ | `true`       |
| `APP_EQUITY_RECALCULATION_INTERVAL` | O intervalo em segundos para recalcular o valor total do portfólio.                                                                                                                                                                                                                                                                                                                     | `300`        |

---

### Banco de Dados (PostgreSQL)

Credenciais para a conexão com o banco de dados PostgreSQL. **Devem ser idênticas às definidas no `docker-compose.yml`**.

| Variável            | Descrição                                 | Valor Padrão   |
| ------------------- | ----------------------------------------- | -------------- |
| `POSTGRES_HOST`     | O endereço do servidor do banco de dados. | `postgres`     |
| `POSTGRES_PORT`     | A porta do servidor do banco de dados.    | `5432`         |
| `POSTGRES_USER`     | Nome de usuário para a conexão.           | `gcs_user`     |
| `POSTGRES_PASSWORD` | Senha para a conexão.                     | `gcs_password` |
| `POSTGRES_DB`       | O nome do banco de dados a ser utilizado. | `gcs_db`       |

---

### Chaves de API da Binance (Binance API Keys)

As chaves de API são essenciais para que o bot possa interagir com sua conta na Binance.

#### Chaves Padrão

Estas chaves são usadas se nenhuma chave específica para o bot (ver abaixo) for encontrada.

| Variável                     | Descrição                                           |
| ---------------------------- | --------------------------------------------------- |
| `BINANCE_API_KEY`            | Sua chave de API para a conta de produção (Live).   |
| `BINANCE_API_SECRET`         | Seu segredo de API para a conta de produção (Live). |
| `BINANCE_TESTNET_API_KEY`    | Sua chave de API para a conta de teste (Testnet).   |
| `BINANCE_TESTNET_API_SECRET` | Seu segredo de API para a conta de teste (Testnet). |

#### Chaves Específicas por Bot (Overrides)

Para gerenciar múltiplos bots, você pode (e deve) usar chaves de API diferentes para cada um. O sistema busca automaticamente por variáveis que seguem o padrão `NOME_DO_BOT_...`.

**Exemplo:** Se `BOT_NAME=meu-bot`, o sistema irá procurar por:

- `MEU_BOT_BINANCE_API_KEY`
- `MEU_BOT_BINANCE_API_SECRET`
- `MEU_BOT_BINANCE_TESTNET_API_KEY`
- `MEU_BOT_BINANCE_TESTNET_API_SECRET`

Se encontradas, essas chaves terão precedência sobre as chaves padrão.

---

### Regras Gerais da Estratégia (Core Trading Strategy Rules)

Controles de alto nível sobre a lógica de negociação e gerenciamento de risco.

| Variável                                             | Descrição                                                                                                                                                                                                                                                                                                                                                                                                                                                                                | Valor Padrão |
| ---------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------ |
| `STRATEGY_RULES_COMMISSION_RATE`                     | Taxa de comissão da exchange (ex: 0.001 para 0.1%). Crucial para calcular o break-even.                                                                                                                                                                                                                                                                                                                                                                                                  | `0.001`      |
| `STRATEGY_RULES_SELL_FACTOR`                         | A porcentagem de uma posição a ser vendida quando o alvo é atingido (1 = 100%).                                                                                                                                                                                                                                                                                                                                                                                                          | `1`          |
| `STRATEGY_RULES_TARGET_PROFIT`                       | **(Legado)** Alvo de lucro base. Geralmente sobrescrito pelos parâmetros de regime.                                                                                                                                                                                                                                                                                                                                                                                                      | `0.0035`     |
| `STRATEGY_RULES_MAX_CAPITAL_PER_TRADE_PERCENT`       | O percentual máximo do capital total que pode ser alocado em uma única operação.                                                                                                                                                                                                                                                                                                                                                                                                         | `0.15`       |
| `STRATEGY_RULES_BASE_USD_PER_TRADE`                  | O valor base em USD para uma operação, se o dimensionamento dinâmico não estiver ativo.                                                                                                                                                                                                                                                                                                                                                                                                  | `10`         |
| `STRATEGY_RULES_MAX_OPEN_POSITIONS`                  | Número máximo de posições abertas simultaneamente.                                                                                                                                                                                                                                                                                                                                                                                                                                       | `150`        |
| `STRATEGY_RULES_USE_DYNAMIC_CAPITAL`                 | **`true`**: Ativa o "Fator de Dificuldade" dinâmico. Após um certo número de compras consecutivas, o robô torna-se progressivamente mais cauteloso, exigindo quedas de preço maiores para comprar. <br>**`false`**: A lógica de dificuldade é desativada. O robô apenas respeitará o limite fixo de `STRATEGY_RULES_MAX_OPEN_POSITIONS`.<br>**Variáveis dependentes (quando `true`)**: `STRATEGY_RULES_CONSECUTIVE_BUYS_THRESHOLD`, `STRATEGY_RULES_DIFFICULTY_RESET_TIMEOUT_HOURS`.     | `true`       |
| `STRATEGY_RULES_WORKING_CAPITAL_PERCENTAGE`          | A porcentagem do capital total que o bot deve considerar como "capital de trabalho".                                                                                                                                                                                                                                                                                                                                                                                                     | `0.85`       |
| `STRATEGY_RULES_USE_FORMULA_SIZING`                  | **`true`**: Ativa o dimensionamento de ordem mais avançado, baseado em uma fórmula logarítmica. O tamanho da ordem (como % do caixa) aumenta ligeiramente à medida que seu portfólio cresce.<br>**`false`**: Usa o método de porcentagem simples (se `USE_PERCENTAGE_BASED_SIZING` for `true`) ou um valor fixo em USD.<br>**Variáveis dependentes (quando `true`)**: `STRATEGY_RULES_MIN_ORDER_PERCENTAGE`, `STRATEGY_RULES_MAX_ORDER_PERCENTAGE`, `STRATEGY_RULES_LOG_SCALING_FACTOR`. | `true`       |
| `STRATEGY_RULES_USE_PERCENTAGE_BASED_SIZING`         | **`true`**: O tamanho da ordem é uma porcentagem fixa do caixa livre. Ativado apenas se `USE_FORMULA_SIZING` for `false`.<br>**`false`**: Se `USE_FORMULA_SIZING` também for `false`, o robô usará um valor fixo em USD (`REGIME_X_ORDER_SIZE_USD`).<br>**Variável dependente (quando `true`)**: `STRATEGY_RULES_ORDER_SIZE_FREE_CASH_PERCENTAGE`.                                                                                                                                       | `true`       |
| `STRATEGY_RULES_USE_REVERSAL_BUY_STRATEGY`           | **`true`**: Ao detectar uma compra por `dip`, o robô aguarda uma pequena reversão de alta antes de comprar, para evitar "comprar facas caindo".<br>**`false`**: O robô compra assim que o alvo de `dip` é atingido.<br>**Variáveis dependentes (quando `true`)**: `STRATEGY_RULES_REVERSAL_BUY_THRESHOLD_PERCENT`, `STRATEGY_RULES_REVERSAL_MONITORING_TIMEOUT_SECONDS`.                                                                                                                 | `true`       |
| `STRATEGY_RULES_REVERSAL_BUY_THRESHOLD_PERCENT`      | A porcentagem que o preço deve subir do ponto mais baixo para confirmar a compra por reversão.                                                                                                                                                                                                                                                                                                                                                                                           | `0.005`      |
| `STRATEGY_RULES_REVERSAL_MONITORING_TIMEOUT_SECONDS` | Tempo em segundos para aguardar a reversão antes de cancelar a tentativa.                                                                                                                                                                                                                                                                                                                                                                                                                | `100`        |
| `STRATEGY_RULES_DIFFICULTY_ADJUSTMENT_FACTOR`        | O multiplicador que aumenta a exigência de compra a cada nível de dificuldade.                                                                                                                                                                                                                                                                                                                                                                                                           | `0.006`      |
| `STRATEGY_RULES_CONSECUTIVE_BUYS_THRESHOLD`          | Número de compras consecutivas que ativa o Fator de Dificuldade.                                                                                                                                                                                                                                                                                                                                                                                                                         | `3`          |
| `STRATEGY_RULES_DIFFICULTY_RESET_TIMEOUT_HOURS`      | Horas sem compras para resetar o Fator de Dificuldade.                                                                                                                                                                                                                                                                                                                                                                                                                                   | `2`          |

---

### Parâmetros de Trailing Stop Dinâmico

Configura a estratégia de trailing stop para maximizar lucros enquanto protege o capital.

| Variável                                      | Descrição                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   | Valor Padrão |
| --------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------ |
| `STRATEGY_RULES_USE_DYNAMIC_TRAILING_STOP`    | **`true`**: Ativa o trailing stop dinâmico. A distância do stop (`trail`) aumenta conforme o lucro aumenta. Isso protege lucros pequenos de forma agressiva e dá mais espaço para a operação "respirar" quando os lucros são maiores.<br>**`false`**: Usa um trailing stop com uma porcentagem **fixa**.<br>**Variáveis dependentes**: <br>- Se `true`: `DYNAMIC_TRAIL_MIN_PCT`, `DYNAMIC_TRAIL_MAX_PCT`, `DYNAMIC_TRAIL_PROFIT_SCALING`.<br>- Se `false`: `DYNAMIC_TRAIL_PERCENTAGE`.<br>_Nota: `TRAILING_STOP_PROFIT` é usado em ambos os modos para a ativação inicial._ | `true`       |
| `STRATEGY_RULES_TRAILING_STOP_PROFIT`         | O valor de lucro em USD que ativa a "trava de segurança" do trailing stop.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  | `0.015`      |
| `STRATEGY_RULES_DYNAMIC_TRAIL_PERCENTAGE`     | **(Legado/Fixo)** A distância percentual do stop se o modo dinâmico estiver desativado.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     | `0.02`       |
| `STRATEGY_RULES_DYNAMIC_TRAIL_MIN_PCT`        | A **porcentagem mínima** inicial do trail quando ele é ativado.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             | `0.01`       |
| `STRATEGY_RULES_DYNAMIC_TRAIL_MAX_PCT`        | A **porcentagem máxima** que o trail pode atingir.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          | `0.05`       |
| `STRATEGY_RULES_DYNAMIC_TRAIL_PROFIT_SCALING` | Fator que controla a rapidez com que o trail aumenta em relação ao lucro.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   | `0.1`        |

---

### Identificadores da Estratégia

Metadados para identificar e restringir a estratégia.

| Variável                               | Descrição                                                        | Valor Padrão       |
| -------------------------------------- | ---------------------------------------------------------------- | ------------------ |
| `TRADING_STRATEGY_NAME`                | Nome descritivo para a estratégia em uso.                        | `default_strategy` |
| `TRADING_STRATEGY_MIN_TRADE_SIZE_USDT` | O valor mínimo em USDT para uma única ordem, conforme a Binance. | `5.0`              |
| `TRADING_STRATEGY_MAX_TRADE_SIZE_USDT` | O valor máximo em USDT para uma única ordem.                     | `1000.0`           |

---

### Parâmetros por Regime de Mercado

O robô pode se adaptar a diferentes condições de mercado. Configure os parâmetros para cada regime.

- **Regime 0:** Baixa Volatilidade / Mercado em Range (Conservador)
- **Regime 1:** Tendência de Alta Moderada (Equilibrado)
- **Regime 2:** Alta Volatilidade / Tendência Forte (Agressivo)
- **Regime 3:** Tendência de Baixa / Cautela (Muito Conservador)

| Variável (substitua `X` pelo número do regime) | Descrição                                                                      |
| ---------------------------------------------- | ------------------------------------------------------------------------------ |
| `REGIME_X_TARGET_PROFIT`                       | O alvo de lucro percentual para este regime.                                   |
| `REGIME_X_BUY_DIP_PERCENTAGE`                  | A porcentagem de queda necessária para iniciar uma compra.                     |
| `REGIME_X_SELL_RISE_PERCENTAGE`                | A porcentagem de lucro que ativa o Trailing Take-Profit.                       |
| `REGIME_X_ORDER_SIZE_USD`                      | O tamanho base da ordem em USD para este regime (se não usar sizing dinâmico). |

---

### Configurações de Backtesting

Parâmetros específicos para a execução de simulações (backtests).

| Variável                         | Descrição                                                                    | Valor Padrão |
| -------------------------------- | ---------------------------------------------------------------------------- | ------------ |
| `BACKTEST_INITIAL_BALANCE`       | O saldo inicial em USDT para iniciar a simulação do backtest.                | `100`        |
| `BACKTEST_COMMISSION_FEE`        | A taxa de comissão por operação a ser simulada no backtest (em porcentagem). | `0.1`        |
| `BACKTEST_DEFAULT_LOOKBACK_DAYS` | O número padrão de dias de dados históricos a serem usados no backtest.      | `30`         |

---

### Configurações de Dados

Define os caminhos e fontes para os dados usados pelo bot.

| Variável                          | Descrição                                                    | Valor Padrão                             |
| --------------------------------- | ------------------------------------------------------------ | ---------------------------------------- |
| `DATA_HISTORICAL_DATA_BUCKET`     | Nome do "bucket" ou agrupamento para dados históricos.       | `btc_data`                               |
| `DATA_PATHS_HISTORICAL_DATA_FILE` | Caminho para o arquivo CSV com os dados históricos de preço. | `data/input/history/BTCUSDT-1m-data.csv` |
| `DATA_PATHS_MACRO_DATA_DIR`       | Diretório para arquivos de dados macroeconômicos.            | `data/input/macro`                       |
| `DATA_PATHS_MODELS_DIR`           | Diretório para salvar modelos de machine learning treinados. | `data/models`                            |

---

### Configurações do Pipeline de Dados

Parâmetros para o pré-processamento de dados e engenharia de features.

| Variável                              | Descrição                                                                         | Valor Padrão                                |
| ------------------------------------- | --------------------------------------------------------------------------------- | ------------------------------------------- |
| `DATA_PIPELINE_FUTURE_PERIODS`        | Número de períodos futuros a serem considerados para a criação de alvos (labels). | `60`                                        |
| `DATA_PIPELINE_PROFIT_MULT`           | Multiplicador para definir o limiar de lucro no labeling.                         | `4.0`                                       |
| `DATA_PIPELINE_STOP_MULT`             | Multiplicador para definir o limiar de stop-loss no labeling.                     | `1.5`                                       |
| `DATA_PIPELINE_REGIME_FEATURES`       | Lista de indicadores técnicos usados para determinar o regime de mercado.         | `["atr_14", "macd_diff_12_26_9", "rsi_14"]` |
| `DATA_PIPELINE_REGIME_ROLLING_WINDOW` | A janela móvel (em períodos) para suavizar os features de regime.                 | `72`                                        |
| `DATA_PIPELINE_START_DATE_INGESTION`  | A data de início para a ingestão de dados históricos.                             | `2023-01-01`                                |

---

### Configurações da API

Se você usar a API interna do bot para monitoramento, estas são as configurações.

| Variável              | Descrição                                             | Valor Padrão |
| --------------------- | ----------------------------------------------------- | ------------ |
| `API_PORT`            | A porta em que a API será executada.                  | `8765`       |
| `API_MEASUREMENT`     | O nome da "medição" ou tabela para os dados de preço. | `price_data` |
| `API_UPDATE_INTERVAL` | O intervalo de atualização da API em segundos.        | `5`          |

## Guia de Uso e Comandos

A interação com o robô é feita principalmente através do script `run.py`. Ele oferece uma interface de linha de comando para gerenciar todo o ciclo de vida do ambiente e dos bots.

### Otimização Walk-Forward (WFO) - Otimização Profissional

Para uma validação verdadeiramente robusta da estratégia, foi implementado um **Adaptive Walk-Forward Optimizer**. Este é o método mais avançado de otimização disponível no projeto.

- **O que é?** Em vez de otimizar usando um único período de dados históricos (o que pode levar a um "superajuste"), o WFO divide o período total em múltiplas janelas de tempo. Ele treina a estratégia em um segmento de dados e, em seguida, a testa em um segmento futuro que a estratégia nunca viu. Esse processo é repetido, deslizando a janela de tempo até o presente.
- **Vantagem:** O resultado final é uma medida muito mais realista de como a estratégia se comportaria em condições de mercado imprevisíveis.
- **Inteligência Adaptativa:** Esta implementação possui "memória". Os melhores parâmetros de uma janela são usados como ponto de partida para a próxima, criando uma estratégia que aprende e se adapta ao longo do tempo.

#### Como Executar o WFO

O WFO é executado diretamente através de seu próprio script, que oferece controle total sobre os períodos de treinamento e teste.

**Uso:**

```bash
python scripts/run_walk_forward_optimizer.py [OPÇÕES]
```

**Opções:**
| Nome | Atalho | Descrição | Padrão |
| --- | --- | --- | --- |
| `--total-days` | `-d` | O número total de dias para todo o período da análise. | `180` |
| `--training-days` | `-t` | O número de dias em cada janela de treino (in-sample). | `60` |
| `--testing-days` | `-v` | O número de dias em cada janela de teste (out-of-sample). | `30` |
| `--trials` | `-n` | O número de testes de otimização a serem executados por janela. | `100` |

**Exemplo de Execução:**

```bash
# Executar um WFO nos últimos 6 meses (180 dias)
# Cada janela terá 60 dias de treino e 30 dias de teste
# O otimizador rodará 200 testes por janela
python scripts/run_walk_forward_optimizer.py --total-days 180 --training-days 60 --testing-days 30 --trials 200
```

**O que acontece:**

1.  **Preparação de Dados:** O script garante automaticamente que todos os dados de minuto a minuto necessários para o período total sejam baixados.
2.  **Loop de Otimização:** O script inicia o loop, otimizando e testando em cada janela.
3.  **Relatório Final:** Ao final, um relatório consolidado é exibido, mostrando o desempenho real (out-of-sample) da estratégia adaptativa ao longo de todo o período.

### Comandos de Gerenciamento do Ambiente

Estes comandos controlam o ambiente Docker subjacente, que inclui o banco de dados PostgreSQL.

---

#### `start-env`

**Descrição:** Garante que os serviços essenciais do ambiente (como o banco de dados PostgreSQL) estejam em execução. Se o ambiente não estiver ativo, este comando irá iniciá-lo.
**Uso:**

```bash
python run.py start-env
```

---

#### `stop-env`

**Descrição:** Para todos os serviços Docker em execução, incluindo os contêineres de bots e o banco de dados. Este comando também remove os contêineres para garantir um estado limpo.
**Uso:**

```bash
python run.py stop-env
```

---

#### `status`

**Descrição:** Mostra o status atual de todos os contêineres Docker associados ao projeto.
**Uso:**

```bash
python run.py status
```

### Comandos de Gerenciamento de Bots

Estes comandos permitem criar, configurar e gerenciar as instâncias de seus bots.

---

#### `new-bot`

**Descrição:** Inicia um guia interativo para criar a configuração de um novo bot. Ele adiciona as variáveis de ambiente necessárias, com o prefixo do nome do bot, ao seu arquivo `.env`.
**Uso:**

```bash
python run.py new-bot
```

**Exemplo de Interação:**

```
Qual o nome do novo bot? (use apenas letras minúsculas, números, '_' e '-', sem espaços) meu-primeiro-bot
✅ Bot 'meu-primeiro-bot' adicionado com sucesso ao seu arquivo .env!
   -> Agora, edite o arquivo e preencha com as chaves de API do bot.
```

---

#### `delete-bot`

**Descrição:** Inicia um guia interativo para remover a configuração de um bot existente do seu arquivo `.env`.
**Uso:**

```bash
python run.py delete-bot
```

---

#### `list-bots`

**Descrição:** Exibe uma tabela com todos os bots que estão atualmente em execução como contêineres Docker.
**Uso:**

```bash
python run.py list-bots
```

---

#### `stop-bot`

**Descrição:** Para um contêiner de bot específico que está em execução. Pode ser usado de forma interativa ou especificando o nome do bot.
**Uso:**

```bash
python run.py stop-bot [OPÇÕES]
```

**Argumentos:**
| Nome | Descrição | Padrão |
| --- | --- | --- |
| `--bot-name, -n` | O nome do bot que você deseja parar. Se não for fornecido, um menu interativo será exibido. | Nenhum |
**Exemplo:**

```bash
# Parar um bot específico
python run.py stop-bot --bot-name meu-primeiro-bot
```

### Comandos de Execução e Monitoramento

Estes comandos são usados para iniciar, monitorar e interagir com seus bots.

---

#### `trade`

**Descrição:** Inicia um bot em modo de produção (**live trading**), utilizando as chaves de API reais da Binance. O bot é executado em segundo plano (modo "detached").
**Uso:**

```bash
python run.py trade [OPÇÕES]
```

**Argumentos:**
| Nome | Descrição | Padrão |
| --- | --- | --- |
| `--bot-name, -n` | **(Obrigatório)** O nome do bot a ser executado. | Nenhum |
| `--detached, -d` | **(Obrigatório)** Deve ser usado para executar o bot em segundo plano. | `True` |
**Exemplo:**

```bash
# Iniciar o bot 'meu-primeiro-bot' em modo de produção
python run.py trade --bot-name meu-primeiro-bot --detached
```

---

#### `test`

**Descrição:** Inicia um bot em modo de teste (**paper trading**), utilizando as chaves de API da Testnet da Binance. O bot é executado em segundo plano.
**Uso:**

```bash
python run.py test [OPÇÕES]
```

**Argumentos:**
| Nome | Descrição | Padrão |
| --- | --- | --- |
| `--bot-name, -n` | **(Obrigatório)** O nome do bot a ser executado. | Nenhum |
| `--detached, -d` | **(Obrigatório)** Deve ser usado para executar o bot em segundo plano. | `True` |
**Exemplo:**

```bash
# Iniciar o bot 'meu-primeiro-bot' em modo de teste
python run.py test --bot-name meu-primeiro-bot --detached
```

---

#### `logs`

**Descrição:** Exibe e acompanha em tempo real os logs de um contêiner de bot em execução. Essencial para depuração.
**Uso:**

```bash
python run.py logs [OPÇÕES]
```

**Argumentos:**
| Nome | Descrição | Padrão |
| --- | --- | --- |
| `--bot-name, -n` | O nome do bot cujos logs você deseja ver. Se não for fornecido, um menu interativo será exibido. | Nenhum |
**Exemplo:**

```bash
# Ver os logs do bot 'meu-primeiro-bot'
python run.py logs --bot-name meu-primeiro-bot
```

---

#### `display`

**Descrição:** Inicia a Interface de Usuário do Terminal (TUI) para monitorar um bot em execução em tempo real.
**Uso:**

```bash
python run.py display [OPÇÕES]
```

**Argumentos:**
| Nome | Descrição | Padrão |
| --- | --- | --- |
| `--bot-name, -n` | O nome do bot que você deseja monitorar. Se não for fornecido, um menu interativo será exibido. | Nenhum |
**Exemplo:**

```bash
# Abrir o painel de monitoramento para o bot 'meu-primeiro-bot'
python run.py display --bot-name meu-primeiro-bot
```

---

#### `backtest`

**Descrição:** Executa um processo de backtesting. Pode ser um backtest simples com os parâmetros atuais ou um fluxo completo de otimização para encontrar os melhores parâmetros. **A preparação dos dados históricos necessários é feita automaticamente.**

**Uso:**

```bash
python run.py backtest [OPÇÕES]
```

**Argumentos:**
| Nome | Descrição | Padrão |
| --- | --- | --- |
| `--bot-name, -n` | O nome do bot para o qual o backtest será executado. Se omitido, será interativo. | `jules_bot` |
| `--days, -d` | O número de dias de dados históricos a serem usados no backtest. | `30` |
| `--optimize` | Se esta flag for usada, ativa o modo de otimização antes do backtest final. | `False` |
| `--jobs, -j` | Número de processos de otimização para rodar em paralelo. | Nº de CPUs da máquina |

**Exemplos de Uso:**

1.  **Backtest Padrão:**
    Executa um backtest simples usando as configurações atuais do seu arquivo `.env`.

    ```bash
    python run.py backtest --bot-name meu-primeiro-bot --days 90
    ```

2.  **Backtest com Otimização:**
    Ativa o fluxo de otimização profissional com um dashboard de monitoramento em tempo real.
    ```bash
    python run.py backtest --optimize
    ```
    - **O que acontece:**
      1.  **Configuração Interativa:** O script fará perguntas para configurar a otimização (número de testes, perfil de carteira, etc.).
      2.  **Dashboard de Otimização:** Um painel de controle (TUI) será iniciado no seu terminal, mostrando o progresso de todos os jobs de otimização em tempo real.
      3.  **Otimização Paralela:** O Optuna rodará vários backtests em segundo plano, de forma eficiente (usando "pruning" para descartar testes ruins), para encontrar a melhor combinação de parâmetros. O progresso é salvo em `optimize/jules_bot_optimization.db` e pode ser retomado de onde parou.
      4.  **Salvar Resultados:** Os melhores parâmetros são salvos automaticamente no arquivo `optimize/.best_params.env`.
      5.  **Backtest Final:** Um último backtest, com relatório detalhado e limpo, é executado usando os parâmetros do `optimize/.best_params.env`.

Este fluxo integrado garante que você possa encontrar e testar a melhor estratégia de forma robusta e profissional com um único comando, agora com visibilidade total do processo.

### Scripts de Utilidade

A pasta `scripts/` contém uma série de ferramentas de linha de comando para interações avançadas, como extração de dados e intervenção manual.

**Requisito Importante:** Para usar esses scripts, você deve ter seu ambiente virtual (`.venv`) ativado, pois eles dependem das bibliotecas instaladas e do código-fonte do projeto.

---

#### `get_trade_history.py`

**Descrição:** Busca o histórico de trades de um bot específico diretamente do banco de dados e o exibe em formato JSON.
**Uso:**

```bash
python scripts/get_trade_history.py [NOME_DO_BOT] [OPÇÕES]
```

**Argumentos:**
| Nome | Descrição | Padrão |
| --- | --- | --- |
| `bot_name` | **(Obrigatório)** O nome do bot para o qual a consulta será feita. | Nenhum |
| `--start-date` | Filtra os trades a partir desta data (YYYY-MM-DD). | Nenhum |
| `--end-date` | Filtra os trades até esta data (YYYY-MM-DD). | Nenhum |
**Exemplo:**

```bash
# Obter todo o histórico do 'meu-primeiro-bot'
python scripts/get_trade_history.py meu-primeiro-bot

# Obter o histórico de Junho de 2024
python scripts/get_trade_history.py meu-primeiro-bot --start-date 2024-06-01 --end-date 2024-06-30
```

---

#### `force_buy.py` e `force_sell.py`

**Descrição:** Estes scripts criam um "arquivo de comando" que instrui um bot em execução a realizar uma compra ou venda manual. O bot monitora a pasta de comandos e executa a ação assim que a detecta. **É necessário definir a variável de ambiente `BOT_NAME` para direcionar o comando ao bot correto.**

**Uso (`force_buy`):**

```bash
export BOT_NAME=meu-primeiro-bot
python scripts/force_buy.py [VALOR_EM_USD]
```

**Argumentos (`force_buy`):**
| Nome | Descrição |
| --- | --- |
| `amount_usd` | **(Obrigatório)** O valor em USD que você deseja comprar. |

**Exemplo (`force_buy`):**

```bash
# Comprar $50 de BTC com o bot 'meu-primeiro-bot'
export BOT_NAME=meu-primeiro-bot
python scripts/force_buy.py 50
```

**Uso (`force_sell`):**

```bash
export BOT_NAME=meu-primeiro-bot
python scripts/force_sell.py [ID_DO_TRADE] [PERCENTUAL]
```

**Argumentos (`force_sell`):**
| Nome | Descrição |
| --- | --- |
| `trade_id` | **(Obrigatório)** O ID único do trade que você deseja vender. |
| `percentage` | **(Obrigatório)** A porcentagem da posição a ser vendida (1 a 100). |

**Exemplo (`force_sell`):**

```bash
# Vender 100% do trade com ID 'abc-123' usando o bot 'meu-primeiro-bot'
export BOT_NAME=meu-primeiro-bot
python scripts/force_sell.py abc-123 100
```

---

#### `run_walk_forward_optimizer.py`

**Descrição:** Executa a otimização Walk-Forward. Veja a seção "Otimização Walk-Forward (WFO)" acima para detalhes completos.
**Uso:** `python scripts/run_walk_forward_optimizer.py --total-days 180 --training-days 60 --testing-days 30`

---

#### `wipe_database.py`

**Descrição:** **(AÇÃO DESTRUTIVA)** Limpa completamente as tabelas do banco de dados para um bot específico. Útil para reiniciar os testes do zero. Requer a variável de ambiente `BOT_NAME`.
**Uso:**

```bash
export BOT_NAME=meu-primeiro-bot
python scripts/wipe_database.py --force
```

**Argumentos:**
| Nome | Descrição |
| --- | --- |
| `--force` | **(Obrigatório)** Confirmação explícita para evitar a exclusão acidental de dados. |

## Entendendo as Métricas de Performance

Tanto o relatório de **backtest** quanto o painel de monitoramento **(TUI)** foram projetados para oferecer uma visão clara e transparente sobre o desempenho do robô. Abaixo está uma explicação detalhada das principais métricas para que você possa interpretar os resultados corretamente.

### Métricas Chave no Painel (TUI) e Relatório de Backtest

| Métrica                        | O que significa?                                                                                                                                                                                                                                                        | Onde Encontrar?        |
| ------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------- |
| **Initial Capital**            | **(TUI)** O valor estimado da sua carteira no momento em que o PnL começou a ser contado. É calculado como: `Valor do Portfólio Atual - Lucro/Prejuízo Líquido`.                                                                                                        | TUI (Painel Principal) |
| **Initial Balance**            | **(Backtest)** O saldo inicial com o qual o backtest começou (ex: $100.00).                                                                                                                                                                                             | Relatório de Backtest  |
| **Portfolio Value**            | **(TUI)** O valor total e atual da sua carteira. É a soma de todo o seu **dinheiro em caixa (não investido)** com o **valor de mercado de todas as suas posições abertas**.                                                                                             | TUI (Painel Principal) |
| **Final Total Balance**        | **(Backtest)** O valor total da carteira ao final da simulação. Equivalente ao "Portfolio Value" da TUI.                                                                                                                                                                | Relatório de Backtest  |
| **Net Profit/Loss**            | **(TUI)** O indicador mais importante do seu resultado financeiro geral. Mostra se você ganhou ou perdeu dinheiro desde o início. É calculado como: `Portfolio Value - Initial Capital`.                                                                                | TUI (Painel Principal) |
| **Net PnL**                    | **(Backtest)** O resultado financeiro total da simulação. Equivalente ao "Net Profit/Loss" da TUI.                                                                                                                                                                      | Relatório de Backtest  |
| **Realized PnL**               | O lucro ou prejuízo **já realizado** com as vendas de posições. Este valor só muda quando uma operação é fechada.                                                                                                                                                       | TUI e Backtest         |
| **Unrealized PnL**             | O lucro ou prejuízo "no papel" de todas as suas posições que **ainda estão abertas**. Este valor flutua constantemente com o preço do mercado.                                                                                                                          | TUI e Backtest         |
| **Open Positions**             | O número de posições de compra que ainda não foram vendidas.                                                                                                                                                                                                            | TUI e Backtest         |
| **Win Rate (Taxa de Vitória)** | A porcentagem de operações de **venda** que foram fechadas com lucro. **Importante:** Esta métrica **não considera as posições abertas**, que podem estar com prejuízo não realizado. É por isso que é possível ter uma alta taxa de vitória e um PnL líquido negativo. | Relatório de Backtest  |

## Entendendo a Tela de Posições Abertas (TUI)

Para acompanhar a estratégia do robô em tempo real, é fundamental entender cada coluna na tela de "Open Positions".

### Diferença Crucial: Target de Venda vs. Trail (Trailing Stop)

**Sim, são duas coisas completamente diferentes.** É a distinção mais importante para entender a estratégia.

1.  **Target de Venda (`sell_rise_percentage`)**:

    - **O que é?** É um **alvo fixo** de lucro, definido no momento da compra. Pense nele como uma ordem de "Take Profit" simples.
    - **Como funciona?** Se você configurou o regime para vender com 0.8% de lucro, o sistema calcula o preço exato que corresponde a esse lucro e define esse preço como o alvo inicial. Se o mercado atingir esse preço, ele vende.
    - **Ponto-chave:** Este alvo **não se move**. Se o preço continuar subindo depois de atingir o alvo, essa lógica simples não captura os lucros adicionais.

2.  **Trail (Trailing Stop)**:
    - **O que é?** É um **alvo dinâmico e inteligente** que é ativado para proteger os lucros e, ao mesmo tempo, permitir que eles continuem a crescer.
    - **Como funciona?**
      - **Ativação:** O trailing stop só é "ativado" depois que a sua posição atinge um lucro mínimo (o `target_profit` do regime).
      - **Rastreamento:** Uma vez ativo, ele não olha mais para o alvo fixo. Em vez disso, ele marca o **pico de lucro** que a operação já atingiu. A ordem de venda passa a ser um percentual (`current_trail_percentage`) _abaixo_ desse pico.
    - **Exemplo Prático:**
      - Sua operação atinge 1% de lucro e o trailing stop de 2% é ativado. O pico de lucro é 1%. O gatilho de venda é 0.98% (2% abaixo de 1%).
      - O mercado continua subindo e seu lucro chega a 5%. O pico agora é 5%. O gatilho de venda se move para 4.9% (2% abaixo de 5%).
      - O mercado vira e o lucro cai para 4.9%. **O robô vende**, garantindo um lucro muito maior do que o alvo fixo inicial.

**Em resumo:** O **Target de Venda** é o plano A (vender com um lucro mínimo). O **Trail** é o plano B (se o lucro continuar subindo, ative um sistema mais inteligente para maximizar os ganhos).

---

### Detalhamento das Colunas

#### Informações Básicas da Posição

- **trade_id**: Identificador único da operação de compra.
- **timestamp**: Data e hora em que a compra foi realizada.
- **entry_price**: O preço médio que você pagou pelo ativo naquela operação.
- **current_price**: O preço atual do ativo no mercado.
- **quantity**: A quantidade do ativo que você possui nesta posição.

#### Lucro e Alvo (PnL - Profit and Loss)

- **unrealized_pnl**: O seu lucro ou prejuízo **atual** em dólar, se você vendesse a posição agora.
- **unrealized_pnl_pct**: O mesmo que o de cima, mas em porcentagem.
- **sell_target_price**: O preço de venda do **alvo fixo** (o nosso "plano A").
- **target_pnl**: O lucro em dólar que você teria se a venda ocorresse no `sell_target_price`.
- **progress_to_sell_target_pct**: O quão perto (em %) você está de atingir o `sell_target_price`.

#### Dados do Trailing Stop (a parte dinâmica)

- **is_smart_trailing_active**: Mostra `True` ou `False`. Indica se o trailing stop já foi ativado para esta posição.
- **smart_trailing_highest_profit**: O **pico de lucro** em dólar que esta posição já alcançou desde que o trailing foi ativado.
- **current_trail_percentage**: O percentual do seu trailing stop. É a "distância" que o lucro pode cair do pico antes de a venda ser acionada.
- **final_trigger_profit**: **Esta é uma das colunas mais importantes.** Mostra o valor exato de lucro em dólar que, se atingido, irá disparar a venda pelo trailing stop.

## Estrutura do Projeto

A estrutura de pastas do projeto foi organizada para separar as responsabilidades e facilitar a manutenção e o desenvolvimento.

- **`/` (Raiz):** Contém os arquivos de configuração principal como `run.py`, `docker-compose.yml`, `requirements.txt` e o `.env`.
- **`jules_bot/`:** O coração da aplicação. Contém toda a lógica do robô.
  - **`bot/`:** Orquestração do bot, gerenciamento de contas e lógica de alto nível.
  - **`core/`:** Lógica de trading principal, regras de estratégia e gerenciamento de estado.
  - **`database/`:** Gerenciamento da conexão e dos modelos do banco de dados (PostgreSQL).
  - **`services/`:** Serviços de suporte, como log de trades e monitoramento de performance.
  - **`utils/`:** Utilitários compartilhados, como o gerenciador de configuração e o logger.
- **`scripts/`:** Contém os scripts de utilidade para interação direta com o bot e o banco de dados.
- **`tui/`:** Código-fonte da Interface de Usuário do Terminal (TUI), construída com a biblioteca Textual.
- **`config/`:** Arquivos de configuração adicionais para serviços como o InfluxDB.
- **`tests/`:** Testes unitários e de integração para garantir a qualidade do código.

## Como Contribuir

Contribuições são bem-vindas! Se você deseja melhorar este projeto, siga estes passos:

1.  **Faça um Fork** do repositório.
2.  **Crie uma Nova Branch** (`git checkout -b feature/sua-feature`).
3.  **Faça suas Alterações** e commite (`git commit -m 'Adiciona nova feature'`).
4.  **Envie para a Branch Original** (`git push origin feature/sua-feature`).
5.  **Abra um Pull Request**.

```

```
