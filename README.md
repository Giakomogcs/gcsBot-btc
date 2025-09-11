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
- [Estrutura do Projeto](#estrutura-do-projeto)
- [Como Contribuir](#como-contribuir)

## Descrição do Projeto

O **Robô de Automação Jules** é um sistema de trading automatizado, robusto e flexível, projetado para operar no mercado de criptomoedas da Binance. Sua arquitetura é centrada em Docker, permitindo que cada bot opere em um contêiner isolado, garantindo estabilidade e escalabilidade. O sistema é controlado por uma poderosa interface de linha de comando (`run.py`) que gerencia todo o ciclo de vida dos bots, desde a criação e configuração até a execução e monitoramento em tempo real.

## Estratégias de Trading Implementadas

As seguintes estratégias foram implementadas para tornar o robô mais inteligente e adaptável às condições de mercado.

### Fator de Dificuldade de Compra Incremental

Para evitar a exaustão de capital durante tendências de baixa prolongadas, o robô emprega um fator de dificuldade de compra que se torna progressivamente mais rigoroso.

- **Como Funciona:** Após um número configurável de compras consecutivas (definido por `STRATEGY_RULES_CONSECUTIVE_BUYS_THRESHOLD`), o robô aumenta a exigência para novas compras. Em vez de comprar após uma queda de X%, ele passará a exigir uma queda de X+1, X+2, e assim por diante.
- **Reset da Dificuldade:** A dificuldade é zerada se ocorrer uma venda ou se não houver novas compras dentro de um período de tempo configurável (`STRATEGY_RULES_DIFFICULTY_RESET_TIMEOUT_HOURS`).

### Trailing Stop Dinâmico com Trava de Lucro

Para maximizar os ganhos e, ao mesmo tempo, proteger o capital, o robô utiliza uma estratégia de trailing stop de nível profissional, que se torna mais flexível à medida que o lucro aumenta.

- **Como Funciona:**

  1.  **Ativação (Trava de Lucro):** Quando uma posição atinge um lucro mínimo em dólar (configurado por `STRATEGY_RULES_TRAILING_STOP_PROFIT`), a "trava de segurança" é ativada. A partir desse ponto, o robô tentará sempre fechar a operação com lucro.
  2.  **Cálculo do Trail Dinâmico:** Em vez de uma porcentagem fixa, o "trail" (a distância do stop ao preço máximo) começa com um valor mínimo e aumenta conforme o lucro da operação cresce. Isso permite um stop mais justo para lucros pequenos e um stop mais flexível para lucros maiores.
  3.  **Lógica de "Não Retorno":** A porcentagem do trail, uma vez que aumenta, **nunca mais diminui** para aquela operação, mesmo que o lucro recue do seu pico. Isso garante que a proteção de lucro seja sempre mantida ou melhorada.
  4.  **Execução:** Se o preço do ativo cair e atingir o preço de stop calculado, a venda é executada. Se, no momento da venda, a operação estiver com prejuízo (devido a uma queda extremamente rápida), a venda é cancelada e o trailing stop é resetado para aguardar uma nova oportunidade de lucro.

- **Benefício:** Esta abordagem permite que o robô "surfe" as tendências de alta de forma mais inteligente. Ele protege lucros pequenos de forma agressiva (com um trail curto) e dá mais espaço para a operação respirar quando os lucros já são significativos (com um trail mais longo), evitando vendas prematuras.

- **Variáveis de Configuração:**

| Variável                                      | Descrição                                                                                                                                   | Valor Padrão |
| --------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- | ------------ |
| `STRATEGY_RULES_USE_DYNAMIC_TRAILING_STOP`    | Ativa (`true`) ou desativa (`false`) a lógica de trailing stop dinâmico. Se `false`, usará a porcentagem fixa definida abaixo.              | `true`       |
| `STRATEGY_RULES_TRAILING_STOP_PROFIT`         | O valor de lucro em USD que ativa a "trava de segurança" do trailing stop.                                                                  | `0.02`       |
| `STRATEGY_RULES_DYNAMIC_TRAIL_PERCENTAGE`     | **(Legado/Fixo)** A distância percentual do stop se o modo dinâmico estiver desativado.                                                     | `0.02`       |
| `STRATEGY_RULES_DYNAMIC_TRAIL_MIN_PCT`        | A **porcentagem mínima** inicial do trail quando ele é ativado.                                                                             | `0.01`       |
| `STRATEGY_RULES_DYNAMIC_TRAIL_MAX_PCT`        | A **porcentagem máxima** que o trail pode atingir, não importa quão alto seja o lucro.                                                      | `0.05`       |
| `STRATEGY_RULES_DYNAMIC_TRAIL_PROFIT_SCALING` | O fator que controla a rapidez com que o trail aumenta em relação ao lucro. Um valor maior torna o trail mais sensível ao aumento de lucro. | `0.1`        |

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

2.  **Edite o arquivo `.env`** e preencha as variáveis essenciais. No mínimo, você precisará configurar suas chaves de API da Binance.

    Abaixo estão as variáveis mais críticas para o funcionamento do robô:

| Variável                     | Descrição                                                      | Exemplo de Valor                  |
| ---------------------------- | -------------------------------------------------------------- | --------------------------------- |
| `POSTGRES_USER`              | Nome de usuário para o banco de dados PostgreSQL.              | `gcs_user`                        |
| `POSTGRES_PASSWORD`          | Senha para o banco de dados PostgreSQL.                        | `gcs_password`                    |
| `POSTGRES_DB`                | Nome do banco de dados a ser utilizado.                        | `gcs_db`                          |
| `BINANCE_API_KEY`            | Sua chave de API para a conta de produção da Binance.          | `AbCdEfGhIjKlMnOpQrStUvWxYz...`   |
| `BINANCE_API_SECRET`         | Seu segredo de API para a conta de produção da Binance.        | `1a2b3c4d5e6f7g8h9i0j1k2l3m4n...` |
| `BINANCE_TESTNET_API_KEY`    | Sua chave de API para a conta de teste (Testnet) da Binance.   | `...`                             |
| `BINANCE_TESTNET_API_SECRET` | Seu segredo de API para a conta de teste (Testnet) da Binance. | `...`                             |

## Configuração Detalhada de Estratégias

Para um controle fino sobre o comportamento do robô, as seguintes variáveis podem ser ajustadas no seu arquivo `.env`.

### Regras Gerais da Estratégia (`STRATEGY_RULES_*`)

Estas variáveis controlam a lógica de alto nível e as salvaguardas da estratégia de trading.

| Variável                                             | Descrição                                                                                                                   | Valor Padrão |
| ---------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------- | ------------ |
| `STRATEGY_RULES_COMMISSION_RATE`                     | A taxa de comissão da exchange (ex: 0.001 para 0.1%). Usada para calcular o preço de break-even.                            | `0.001`      |
| `STRATEGY_RULES_SELL_FACTOR`                         | A porcentagem de uma posição a ser vendida quando o alvo de lucro é atingido (ex: 1 para vender 100%, 0.5 para vender 50%). | `1`          |
| `STRATEGY_RULES_MAX_OPEN_POSITIONS`                  | O número máximo de posições que o robô pode manter abertas simultaneamente.                                                 | `150`        |
| `STRATEGY_RULES_USE_DYNAMIC_CAPITAL`                 | Se `true`, ativa lógicas dinâmicas como o fator de dificuldade.                                                             | `true`       |
| `STRATEGY_RULES_WORKING_CAPITAL_PERCENTAGE`          | A porcentagem do capital total da carteira que deve ser usada para trading ativo.                                           | `0.85`       |
| `STRATEGY_RULES_USE_REVERSAL_BUY_STRATEGY`           | Se `true`, ativa a estratégia que monitora por uma reversão de preço antes de confirmar uma compra em um dip.               | `true`       |
| `STRATEGY_RULES_REVERSAL_BUY_THRESHOLD_PERCENT`      | A porcentagem que o preço precisa subir do ponto mais baixo para confirmar uma compra por reversão.                         | `0.005`      |
| `STRATEGY_RULES_REVERSAL_MONITORING_TIMEOUT_SECONDS` | O tempo em segundos que o robô monitora por uma reversão antes de cancelar a tentativa de compra.                           | `100`        |
| `STRATEGY_RULES_CONSECUTIVE_BUYS_THRESHOLD`          | O número de compras consecutivas antes que o fator de dificuldade comece a ser aplicado.                                    | `5`          |
| `STRATEGY_RULES_DIFFICULTY_ADJUSTMENT_FACTOR`        | O multiplicador usado para aumentar a exigência de compra a cada nível de dificuldade.                                      | `0.005`      |
| `STRATEGY_RULES_DIFFICULTY_RESET_TIMEOUT_HOURS`      | O número de horas sem compras após o qual o fator de dificuldade é resetado.                                                | `2`          |

### Parâmetros por Regime de Mercado (`REGIME_*`)

O robô identifica 4 regimes de mercado e aplica um conjunto diferente de parâmetros para cada um, permitindo uma estratégia adaptativa.

- **Regime 0:** Baixa Volatilidade / Mercado em Range (Estratégia Conservadora)
- **Regime 1:** Tendência de Alta Moderada (Estratégia Equilibrada)
- **Regime 2:** Alta Volatilidade / Tendência Forte (Estratégia Agressiva)
- **Regime 3:** Tendência de Baixa / Cautela (Estratégia Muito Conservadora)

| Variável                        | Descrição                                                                                | Valor Padrão (Regime 1) |
| ------------------------------- | ---------------------------------------------------------------------------------------- | ----------------------- |
| `REGIME_X_BUY_DIP_PERCENTAGE`   | A porcentagem de queda a partir de um topo recente necessária para iniciar uma compra.   | `0.003`                 |
| `REGIME_X_SELL_RISE_PERCENTAGE` | A porcentagem de lucro inicial que, ao ser atingida, ativa o Trailing Take-Profit.       | `0.008`                 |
| `REGIME_X_ORDER_SIZE_USD`       | O tamanho base da ordem em USD para este regime (se não estiver usando sizing dinâmico). | `10`                    |

_Substitua `X` pelo número do regime (0, 1, 2 ou 3) para configurar cada um individualmente._

## Guia de Uso e Comandos

A interação com o robô é feita principalmente através do script `run.py`. Ele oferece uma interface de linha de comando para gerenciar todo o ciclo de vida do ambiente e dos bots.

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

**Descrição:** Executa um processo de backtesting. Pode ser um backtest simples com os parâmetros atuais ou um fluxo completo de otimização para encontrar os melhores parâmetros antes da simulação final.

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
    Ativa o fluxo de otimização profissional.
    ```bash
    python run.py backtest --optimize
    ```
    - **O que acontece:**
        1.  **Configuração Interativa:** O script fará perguntas para configurar a otimização (número de testes, perfil de carteira, etc.).
        2.  **Otimização:** O Optuna rodará vários backtests em segundo plano, de forma eficiente (usando "pruning" para descartar testes ruins), para encontrar a melhor combinação de parâmetros. O progresso é salvo em `jules_bot_optimization.db`.
        3.  **Salvar Resultados:** Os melhores parâmetros são salvos automaticamente no arquivo `.best_params.env`.
        4.  **Backtest Final:** Um último backtest, com relatório detalhado e limpo, é executado usando os parâmetros do `.best_params.env`.

Este fluxo integrado garante que você possa encontrar e testar a melhor estratégia de forma robusta e profissional com um único comando.

### Scripts de Utilidade

A pasta `scripts/` contém uma série de ferramentas de linha de comando para interações avançadas, como extração de dados e intervenção manual.

**Requisito Importante:** Para usar esses scripts, você deve ter seu ambiente virtual (`.venv`) ativado, pois eles dependem das bibliotecas instaladas e do código-fonte do projeto.

---

#### `get_trade_history.py`
**Descrição:** Busca o histórico de trades de um bot específico diretamente do banco de dados e o exibe em formato JSON.
**Uso:**
```bash
python scripts/get_trade_history.py [NOME_DO_BOT] [OPÇÕES]
````

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
