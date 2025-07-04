# 📈 gcsBot - Framework de Trading Quantitativo para BTC/USDT

![Python](https://img.shields.io/badge/Python-3.11+-blue.svg) ![Docker](https://img.shields.io/badge/Docker-Ready-blue?logo=docker) ![License](https://img.shields.io/badge/License-MIT-green.svg)

Um framework de ponta para pesquisa, validação e execução de estratégias de trading algorítmico no par BTC/USDT. Este projeto vai além de um simples bot, oferecendo um pipeline completo de Machine Learning, desde a otimização de estratégias com dados históricos até a operação autônoma e adaptativa na Binance.

---

## 📋 Tabela de Conteúdos

- [🌟 Sobre o Projeto](#-sobre-o-projeto)
- [✨ Features de Destaque](#-features-de-destaque)
- [🧠 A Filosofia do Bot: Como Ele Pensa?](#-a-filosofia-do-bot-como-ele-pensa)
- [⚙️ Ecossistema do Bot: Como os Módulos Interagem](#️-ecossistema-do-bot-como-os-módulos-interagem)
- [🚀 Guia de Início Rápido](#-guia-de-início-rápido)
- [🔧 Configuração do Ambiente (`.env`)](#-configuração-do-ambiente-env)
- [▶️ O Workflow Profissional: Como Usar](#️-o-workflow-profissional-como-usar)
- [📂 Estrutura do Projeto](#-estrutura-do-projeto)
- [📜 Licença](#-licença)

---

## 🌟 Sobre o Projeto

Este repositório contém um sistema de trading algorítmico completo, projetado para ser robusto, inteligente e metodologicamente correto. Diferente de bots baseados em regras fixas, o gcsBot utiliza um modelo de **Machine Learning (LightGBM)** para encontrar padrões preditivos e uma arquitetura sofisticada para se adaptar às dinâmicas do mercado.

O núcleo do projeto é um processo de **Walk-Forward Optimization (WFO)** que garante que a estratégia seja constantemente reavaliada e otimizada em dados novos, evitando o overfitting e a estagnação. O resultado é um agente autônomo que não apenas opera, mas aprende e se ajusta.

---

## ✨ Features de Destaque

- **🧠 Inteligência Multi-Camada:**

  - **Gestão Ativa de Posição:** Uma vez em um trade, o bot gerencia ativamente o risco com técnicas de **Breakeven Stop, Realização de Lucro Parcial e Trailing Stop**.
  - **Estratégia de Duplo Objetivo:** O bot não só busca lucro em USDT, mas também o utiliza para **acumular um "Tesouro de BTC"** a longo prazo, alocando uma porcentagem dos lucros para essa finalidade.
  - **Confiança Dinâmica:** O bot ajusta sua própria "coragem" com base na performance de uma **janela de trades recentes**, tornando-se mais ousado em sequências de vitórias e mais cauteloso após perdas.
  - **Risco Dinâmico (Bet Sizing):** O tamanho de cada operação é proporcional à convicção do modelo e ao regime de mercado atual, arriscando de forma inteligente.

- **🤖 Metodologia de Nível Profissional:**

  - **Otimização Robusta (Calmar Ratio):** O sistema utiliza `Optuna` para otimizar a estratégia buscando o melhor **Calmar Ratio** (Retorno Anualizado / Máximo Drawdown), priorizando a segurança do capital.
  - **Filtro de Regime de Mercado:** O bot primeiro identifica o estado do mercado (ex: `BULL_FORTE`, `BEAR`, `LATERAL`) e ajusta seu comportamento de risco ou até mesmo bloqueia operações.
  - **Validação Robusta (Train/Validate/Test):** O processo de otimização utiliza uma metodologia rigorosa que impede o vazamento de dados do futuro (_look-ahead bias_).

- **⚙️ Engenharia de Ponta:**
  - **Backtest Realista:** Todas as simulações incluem custos operacionais (taxas e slippage) para uma avaliação de performance fiel à realidade.
  - **Atualização Automática de Dados:** Coleta e atualiza automaticamente não só os dados de cripto da Binance, mas também os **dados macroeconômicos** (DXY, Ouro, VIX, TNX) via `yfinance`.
  - **Deployment com Docker:** Ambiente 100% conteinerizado para uma execução consistente e livre de problemas de dependências.
  - **Logs e Visualização Avançados:** Utiliza `tqdm` e `tabulate` para oferecer barras de progresso e relatórios claros e fáceis de ler.

---

## 🧠 A Filosofia do Bot: Como Ele Pensa?

A tomada de decisão do gcsBot segue uma **hierarquia de inteligência em 3 camadas**, imitando uma estrutura de comando militar para garantir decisões robustas e bem fundamentadas:

### **Camada 1: O General (Estratégia)**

- **Pergunta:** "O campo de batalha é favorável? Devemos lutar hoje?"
- **Ação:** Analisa o **regime de mercado** de longo prazo (`BULL_FORTE`, `BEAR`, etc.) usando médias móveis diárias. Com base nesse cenário, ele define a política de risco geral: se os trades são permitidos e qual o nível de agressividade. Em um regime `BEAR`, o General pode ordenar a retirada total, preservando o capital.

### **Camada 2: O Capitão (Tática)**

- **Pergunta:** "Dado que o General deu sinal verde, este é o momento exato para atacar?"
- **Ação:** O **modelo de Machine Learning**, treinado com dados recentes e ciente do regime de mercado, busca por padrões de curto prazo que indiquem uma oportunidade de compra com alta probabilidade. Ele gera um sinal de "confiança de compra".

### **Camada 3: O Soldado (Execução e Gestão)**

- **Pergunta:** "Ataque iniciado. Como gerenciamos esta posição para maximizar ganhos e minimizar perdas?"
- **Ação:** Uma vez que a compra é executada, este módulo assume o controle com regras precisas:
  1.  **Proteção:** Move o stop para o _breakeven_ assim que o trade atinge um pequeno lucro, eliminando o risco sobre o capital principal.
  2.  **Realização:** Garante parte do lucro vendendo uma fração da posição ao atingir o alvo de lucro.
  3.  **Maximização:** Deixa o restante da posição "correr" com um _trailing stop_ para capturar tendências maiores.
  4.  **Tesouraria:** Aloca uma parte do lucro realizado para o "Tesouro de BTC", cumprindo o objetivo de acumulação de longo prazo.

Este processo transforma o bot de um simples executor de sinais em um agente estratégico que pensa em múltiplas camadas.

---

## ⚙️ Ecossistema do Bot: Como os Módulos Interagem

- **`optimizer.py`**: O cérebro da pesquisa. Gerencia o WFO, chama o `model_trainer` e o `backtest`, e usa o `Optuna` para encontrar os melhores parâmetros para a estratégia completa, otimizando pelo Calmar Ratio.
- **`model_trainer.py`**: O "cientista de dados". Prepara todas as features (técnicas, macro e de regime) e treina o modelo LightGBM para que ele entenda o contexto do mercado.
- **`confidence_manager.py`**: O "psicólogo" do bot. Implementa a lógica para ajustar a confiança com base na performance recente, tornando-o mais estável.
- **`backtest.py`**: O simulador de combate. Executa a estratégia Multi-Camada completa de forma realista para fornecer as métricas de performance (Drawdown, Retorno) para o otimizador.
- **`quick_tester.py`**: O "auditor". Permite validar um modelo já treinado em um período de tempo futuro, gerando um relatório completo com as novas métricas de performance.
- **`trading_bot.py`**: O "piloto de elite". Módulo que opera no mercado real, implementando a mesma estratégia Multi-Camada validada na otimização.

---

## 🚀 Guia de Início Rápido

Siga estes passos para colocar o bot em funcionamento.

### Pré-requisitos

- [Python 3.11+](https://www.python.org/downloads/)
- [Git](https://git-scm.com/downloads)
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (em execução)

### Instalação

1.  **Clone o repositório:**
    ```bash
    git clone https://github.com/SEU_USUARIO/gcsbot-btc.git
    cd gcsbot-btc
    ```
2.  **Execute o Setup Automático:**
    Este comando irá verificar o ambiente, instalar as dependências e criar o seu arquivo de configuração `.env`.

    ```bash
    python run.py setup
    ```

    > ⚠️ **Atenção:** Após o setup, abra o arquivo `.env` recém-criado e preencha **todas** as variáveis, especialmente suas chaves de API.

3.  **Construa a Imagem Docker:**
    ```bash
    python run.py build
    ```

---

## 🔧 Configuração do Ambiente (`.env`)

O arquivo `.env` é o painel de controle principal do bot.

- **`MODE`**: Modo de operação: `optimize`, `backtest`, `test`, ou `trade`.
- **`FORCE_OFFLINE_MODE`**: `True` ou `False`. Impede o bot de acessar a internet (útil para otimizações).

#### Chaves de API

- `BINANCE_API_KEY` & `BINANCE_API_SECRET`: Chaves da conta **real**.
- `BINANCE_TESTNET_API_KEY` & `BINANCE_TESTNET_API_SECRET`: Chaves da conta **Testnet**.

#### Gestão de Portfólio (Para os modos `test` e `trade`)

- `MAX_USDT_ALLOCATION`: O **MÁXIMO** de capital em USDT que o bot tem permissão para gerenciar na sua parte de trading.

---

## ▶️ O Workflow Profissional: Como Usar

A interação com o bot é feita através do orquestrador `run.py`. Siga estas fases na ordem correta.

### Passo Zero: Limpeza do Ambiente (MUITO IMPORTANTE)

Antes de iniciar uma **nova** otimização para uma estratégia reformulada, é essencial apagar os artefatos antigos para garantir que o sistema comece do zero, sem nenhuma informação da estratégia anterior.

**Apague os seguintes arquivos do seu diretório `/data`:**

- `model.joblib`
- `scaler.joblib`
- `strategy_params.json`
- `wfo_optimization_state.json`
- `combined_data_cache.csv`

### Fase 1: Pesquisa e Otimização (`optimize`)

O passo mais importante. O bot irá estudar todo o histórico para encontrar a melhor estratégia e criar os arquivos de modelo.

```bash
python run.py optimize
```

Este processo é longo e pode levar horas ou dias. Ao final, os arquivos `trading_model.pkl`, `scaler.pkl` e `strategy_params.json` serão salvos na pasta /data.

---

### Fase 2: Backtest Rápido

Após a otimização, valide a nova estratégia em um período que o modelo nunca viu durante o treino.

```bash
python run.py backtest --start "2024-01-01" --end "2025-01-01"
```

O bot irá rodar a simulação e imprimir um relatório de performance completo, incluindo Calmar Ratio e o Tesouro de BTC acumulado.

---

### Fase 3: Validação em Testnet

Se a validação for positiva, teste a estratégia no mercado ao vivo com dinheiro de teste.

```bash
python run.py test
```

Ele usará o modelo e os parâmetros criados na Fase 1. Deixe rodando por pelo menos 1-2 semanas para observar o comportamento em tempo real.

---

### Fase 3: Trading Real

O passo final. O bot operará da mesma forma que no modo test, mas utilizando sua conta real da Binance e sua alocação de capital definida.

```bash
python run.py trade
```

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
│   ├── backtest.py        # Motor de simulação realista (usado pela otimização)
│   ├── config.py          # Gerenciador de configurações do .env
│   ├── confidence_manager.py # Cérebro da confiança adaptativa
│   ├── data_manager.py    # Gerenciador de coleta e cache de dados
│   ├── logger.py          # Configuração do sistema de logs
│   ├── model_trainer.py   # Prepara features e treina o modelo de ML
│   ├── optimizer.py       # Orquestrador do Walk-Forward Optimization (WFO)
│   ├── quick_tester.py    # Lógica para o modo de backtest rápido (validação)
│   └── trading_bot.py     # Lógica de operação real e gestão de portfólio
├── .dockerignore          # Arquivos a serem ignorados pelo Docker
├── .env.example           # Exemplo do arquivo de configuração
├── .gitignore             # Arquivos a serem ignorados pelo Git
├── Dockerfile             # Define o ambiente Docker para o bot
├── main.py                # Ponto de entrada principal (usado pelo Docker)
├── README.md              # Esta documentação
├── requirements.txt       # Dependências Python
└── run.py                 # Orquestrador principal e ponto de entrada do usuário
```
