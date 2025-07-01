# 📈 gcsBot - Bot de Trading para BTC/USDT com Machine Learning

![Python](https://img.shields.io/badge/Python-3.12-blue.svg) ![License](https://img.shields.io/badge/License-MIT-green.svg) ![Docker](https://img.shields.io/badge/Docker-Ready-blue?logo=docker)

Um bot de trading algorítmico de nível profissional para o par BTC/USDT na Binance, que utiliza técnicas avançadas de Machine Learning e gestão de portfólio dinâmica para otimizar estratégias e operar de forma autônoma.

---

## 📋 Tabela de Conteúdos

- [Sobre o Projeto](#-sobre-o-projeto)
- [✨ Core Features](#-core-features)
- [🧠 Como o Bot "Pensa"? (A Estratégia)](#-como-o-bot-pensa-a-estratégia)
- [⚙️ O Ecossistema do Bot: Como os Módulos Interagem](#️-o-ecossistema-do-bot-como-os-módulos-interagem)
- [🚀 Começando](#-começando)
  - [Pré-requisitos](#pré-requisitos)
  - [Instalação](#instalação)
- [🔧 Configuração do Ambiente (`.env`)](#-configuração-do-ambiente-env)
- [▶️ Como Usar (Workflow Profissional)](#️-como-usar-workflow-profissional)
  - [Fase 1: Otimização (`optimize`)](#fase-1-otimização-optimize)
  - [Fase 2: Backtest Rápido (`backtest`)](#fase-2-backtest-rápido-backtest)
  - [Fase 3: Validação em Testnet (`test`)](#fase-3-validação-em-testnet-test)
  - [Fase 4: Produção (`trade`)](#fase-4-produção-trade)
  - [Comandos Adicionais](#comandos-adicionais)
- [📂 Estrutura do Projeto](#-estrutura-do-projeto)
- [📜 Licença](#-licença)

---

## 🤖 Sobre o Projeto

Este não é um bot de trading comum. Ele foi projetado para tomar decisões baseadas em dados e estatísticas, não em regras fixas. O sistema utiliza um pipeline completo de Machine Learning e um gerenciador de portfólio para:

1.  **Aprender** com um vasto histórico de dados de mercado para prever oportunidades.
2.  **Gerenciar o Risco** de forma dinâmica, ajustando o tamanho de cada operação com base no capital disponível.
3.  **Otimizar** seus próprios parâmetros através de um processo robusto de Walk-Forward Optimization (WFO).
4.  **Validar** a estratégia otimizada em dados futuros "não vistos" para garantir a robustez.
5.  **Operar** de forma autônoma nos ambientes de Teste (Testnet) ou Produção (Conta Real) da Binance.

O objetivo é encontrar e explorar ineficiências no mercado, combinando análise técnica e macroeconômica, sempre sob uma camada de gestão de capital disciplinada.

---

## ✨ Core Features

- **🧠 Modelo Preditivo (LightGBM):** Utiliza um modelo de Gradient Boosting rápido e eficiente para encontrar padrões nos dados.
- **💼 Gestão de Portfólio Dinâmica:** Gerencia o capital de forma inteligente, separando fundos para holding e para trading, com cálculo de risco percentual dinâmico por operação.
- **🔍 Otimização de Hiperparâmetros (Optuna):** Encontra a melhor combinação de parâmetros para o modelo e para a estratégia em cada janela de tempo.
- **🛡️ Walk-Forward Optimization (WFO):** A metodologia de backtesting mais robusta, que simula o desempenho do bot em condições de mercado dinâmicas, forçando-o a se adaptar continuamente.
- **ρεαλισμός Backtest Realista:** A simulação de backtest inclui **custos operacionais** (taxas e slippage) e é livre de **look-ahead bias**, garantindo que os resultados da otimização sejam honestos.
- **💵 Integração de Dados Macroeconômicos:** Incorpora a variação horária de múltiplos indicadores (DXY, VIX, Ouro, Títulos de 10 anos) como features para um rico contexto de mercado.
- **🚀 Cache Inteligente de Dados:** Salva os dados pré-processados e unificados, permitindo uma inicialização quase instantânea nas execuções seguintes e viabilizando o modo offline.
- **🔌 Modo Offline Robusto:** Permite rodar a otimização inteira sem conexão com a internet (usando dados locais e de cache) e possui travas de segurança que impedem o início dos modos de trade real/teste se a internet não estiver disponível.
- **🐳 Deployment com Docker:** Empacotado em um container Docker para um deployment fácil, portátil e consistente entre diferentes máquinas.
- **▶️ Orquestrador Inteligente (`run.py`):** Um ponto de entrada único que gerencia todo o ciclo de vida do bot, desde a instalação até a execução dos diferentes modos.
- **📝 Logging Detalhado:** Sistema de logs inteligente que registra não apenas os trades, mas o estado completo do portfólio e o progresso da otimização.

---

## 🧠 Como o Bot "Pensa"? (A Estratégia)

O bot é um especialista em encontrar **padrões numéricos** nos dados de mercado. Ele analisa uma combinação de "impressões digitais" (features) de volatilidade, tendência, momento e macroeconomia para tomar uma decisão. Quando o modelo encontra um padrão com alta probabilidade estatística de sucesso, ele passa a decisão para o **Gerenciador de Portfólio**, que calcula o tamanho exato da posição com base nas regras de risco definidas, garantindo que nenhuma operação individual possa comprometer o capital total.

---

## ⚙️ O Ecossistema do Bot: Como os Módulos Interagem

O bot opera em diferentes modos, utilizando combinações específicas de arquivos.

#### Modo de Otimização (`optimize`)

Neste modo, o bot está em seu "laboratório de pesquisa".

- **`optimizer.py`**: É o cérebro da operação. Ele gerencia o processo de Walk-Forward.
- **`model_trainer.py`**: É chamado pelo otimizador para treinar um novo modelo a cada ciclo.
- **`backtest.py`**: Para cada modelo treinado, executa uma simulação realista. O resultado (Sharpe Ratio) é devolvido ao otimizador.
- **Resultado Final:** A criação dos arquivos `trading_model.pkl`, `scaler.pkl` e `strategy_params.json` na pasta `/data`.

#### Modo de Backtest Rápido (`backtest`)

Um modo de validação para testar o modelo mais recente em um período futuro.

- **`quick_tester.py`**: O módulo principal deste modo. Ele carrega os arquivos gerados pela otimização.
- **Simulação Realista:** Executa uma simulação vela a vela no período de teste definido, usando a mesma lógica de gestão de portfólio do modo de trade real.
- **Resultado Final:** Um relatório detalhado de performance mês a mês impresso no terminal.

#### Modos de Operação (`test` e `trade`)

Neste modo, o bot está "em campo", operando no mercado ao vivo.

- **`trading_bot.py`**: É o único módulo ativo. Ele é o piloto.
- **`PortfolioManager`**: Uma classe dentro do `trading_bot.py` que gerencia ativamente o capital, calcula o tamanho das posições e protege a carteira.
- **Conexão com a Binance**: Usa as chaves de API para enviar ordens para a Testnet (modo `test`) ou para a conta real (modo `trade`).

---

## 🚀 Começando

Siga estes passos para colocar o bot em funcionamento.

### Pré-requisitos

- [Python 3.10+](https://www.python.org/downloads/)
- [Git](https://git-scm.com/downloads)
- [Docker Desktop](https://www.docker.com/products/docker-desktop/)

### Instalação

1.  **Clone o repositório:**
    ```bash
    git clone [https://github.com/giakomogcs/gcsbot-btc.git](https://github.com/giakomogcs/gcsbot-btc.git)
    cd gcsbot-btc
    ```
2.  **Execute o Setup Automático:**
    ```bash
    python run.py setup
    ```
    ⚠️ **Atenção:** Este comando criará um arquivo `.env`. **Você deve abri-lo e preencher todas as variáveis necessárias.**
3.  **Construa a Imagem Docker:**
    ```bash
    python run.py build
    ```

---

## 🔧 Configuração do Ambiente (`.env`)

O arquivo `.env` é o painel de controle principal do bot.

- **`MODE`**: Define o modo de operação. Use `optimize`, `backtest`, `test`, ou `trade`.
- **`SYMBOL`**: O par de moedas a ser operado (ex: `BTCUSDT`).
- **`FORCE_OFFLINE_MODE`**: `True` ou `False`. Se `True`, o bot não tentará nenhuma conexão com a internet e usará apenas dados locais/em cache. Impede a execução dos modos `test` e `trade`.

#### Chaves de API

- `BINANCE_API_KEY` & `BINANCE_API_SECRET`: Suas chaves da conta **real**.
- `BINANCE_TESTNET_API_KEY` & `BINANCE_TESTNET_API_SECRET`: Suas chaves da conta **Testnet**.

#### Gestão de Portfólio

- `MAX_USDT_ALLOCATION`: O **MÁXIMO** de capital em USDT que o bot tem permissão para gerenciar.
- `LONG_TERM_HOLD_PCT`: Percentual do capital que será usado para comprar e manter BTC como holding. Ex: `0.50` para 50%.
- `RISK_PER_TRADE_PCT`: Do capital de **trading** restante, qual a porcentagem de risco por operação? Ex: `0.02` para arriscar 2%.

#### Backtest Rápido

- `BACKTEST_START_DATE` & `BACKTEST_END_DATE`: Define o período para a simulação do modo `backtest`. Ex: `2025-01-01`.

> ⚠️ **Nunca compartilhe ou envie seu arquivo `.env` para repositórios públicos!**

---

## ▶️ Como Usar (Workflow Profissional)

A interação com o bot é feita através do orquestrador `run.py`. Siga estas fases na ordem correta.

### Fase 1: Otimização

O passo mais importante. O bot irá estudar todo o histórico para encontrar a melhor estratégia e criar os arquivos de modelo.

```bash
python run.py optimize
```

Este processo é longo e pode levar horas ou dias. Ao final, os arquivos `trading_model.pkl`, `scaler.pkl` e `strategy_params.json` serão salvos na pasta /data.

---

### Fase 2: Backtest Rápido

Após a otimização, valide a estratégia no mercado ao vivo com dinheiro de teste.

```bash
python run.py backtest
```

O bot irá rodar a simulação no período definido no .env e imprimir um relatório de performance mês a mês no terminal.

---

### Fase 3: Validação em Testnet

Após a otimização, valide a estratégia no mercado ao vivo com dinheiro de teste.

```bash
python run.py test
```

O bot iniciará em segundo plano e rodará 24/7. Ele usará o modelo e os parâmetros criados na Fase 1. Deixe rodando por pelo menos 1-2 semanas para obter dados estatísticos relevantes.

---

### Fase 3: Trading Real

Após a otimização, valide a estratégia no mercado ao vivo com dinheiro de teste.

```bash
python run.py trade
```

O bot operará da mesma forma que no modo test, mas utilizando sua conta real da Binance.

---

## Comandos Adicionais

- Ver os Logs em Tempo Real:

```bash
python run.py logs
```

- Parar o Bot (Modo `test` ou `trade`):

```bash
python run.py stop
```

---

# 📂 Estrutura do Projeto

```bash
gcsbot-btc/
├── data/                  # Dados gerados (CSVs, modelos, estados) - Ignorado pelo Git
├── logs/                  # Arquivos de log diários - Ignorado pelo Git
├── src/                   # Código fonte do projeto
│   ├── __init__.py
│   ├── backtest.py        # Módulo de backtesting para a otimização
│   ├── config.py          # Carrega e gerencia as configurações
│   ├── data_manager.py    # Gerencia a coleta, unificação e cache de dados
│   ├── logger.py          # Configuração do sistema de logs
│   ├── model_trainer.py   # Prepara features e treina o modelo de ML
│   ├── optimizer.py       # Orquestra o Walk-Forward Optimization
│   ├── quick_tester.py    # Lógica para o modo de backtest rápido
│   └── trading_bot.py     # Lógica de operação e gestão de portfólio
├── .dockerignore          # Arquivos a serem ignorados pelo Docker
├── .env.example           # Exemplo do arquivo de configuração
├── .gitignore             # Arquivos a serem ignorados pelo Git
├── Dockerfile             # Define o ambiente Docker para o bot
├── main.py                # Ponto de entrada (usado pelo Docker)
├── README.md              # Esta documentação
├── requirements.txt       # Dependências Python
└── run.py                 # Orquestrador principal e ponto de entrada do usuário
```
