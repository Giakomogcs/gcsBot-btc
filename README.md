# gcsBot - A Quantitative Trading Framework

[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Docker](https://img.shields.io/badge/Docker-Ready-blue?logo=docker)](https://www.docker.com/products/docker-desktop/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)

**gcsBot** is a state-of-the-art framework for algorithmic trading on the BTC/USDT pair. This project provides a complete Machine Learning pipeline, from strategy optimization with historical data to autonomous and adaptive operation on Binance.

## Table of Contents

- [About the Project](#about-the-project)
- [Key Features](#key-features)
- [The Bot's Philosophy](#the-bots-philosophy)
- [The Bot's Ecosystem](#the-bots-ecosystem)
- [Quick Start Guide](#quick-start-guide)
- [Environment Configuration](#environment-configuration)
- [The Professional Workflow](#the-professional-workflow)
- [Project Structure](#project-structure)
- [License](#license)

## About the Project

This repository contains a complete algorithmic trading system, designed to be robust, intelligent, and methodologically sound. Unlike bots based on fixed rules, gcsBot uses a **Machine Learning (LightGBM)** model to find predictive patterns and a sophisticated architecture to adapt to market dynamics.

The core of the project is a **Walk-Forward Optimization (WFO)** process that ensures that the strategy is constantly re-evaluated and optimized on new data, avoiding overfitting and stagnation. The result is an autonomous agent that not only operates, but also learns and adjusts.

## Key Features

- **Multi-Layered Intelligence:**
  - **Active Position Management:** Once in a trade, the bot actively manages risk with **Breakeven Stop, Partial Profit Taking, and Trailing Stop** techniques.
  - **Dual Objective Strategy:** The bot not only seeks profit in USDT, but also uses it to **accumulate a "BTC Treasury"** in the long term, allocating a percentage of the profits for this purpose.
  - **Dynamic Confidence:** The bot adjusts its own "courage" based on the performance of a **window of recent trades**, becoming bolder in winning streaks and more cautious after losses.
  - **Dynamic Risk (Bet Sizing):** The size of each operation is proportional to the model's conviction and the current market regime, risking intelligently.

- **Professional-Level Methodology:**
  - **Robust Optimization (Calmar Ratio):** The system uses `Optuna` to optimize the strategy by seeking the best **Calmar Ratio** (Annualized Return / Maximum Drawdown), prioritizing capital security.
  - **Market Regime Filter:** The bot first identifies the state of the market (e.g., `BULL_FORTE`, `BEAR`, `LATERAL`) and adjusts its risk behavior or even blocks operations.
  - **Robust Validation (Train/Validate/Test):** The optimization process uses a rigorous methodology that prevents data leakage from the future (_look-ahead bias_).

- **Cutting-Edge Engineering:**
  - **Realistic Backtest:** All simulations include operational costs (fees and slippage) for a performance evaluation that is faithful to reality.
  - **Automatic Data Update:** Automatically collects and updates not only crypto data from Binance, but also **macroeconomic data** (DXY, Gold, VIX, TNX) via `yfinance`.
  - **Deployment with Docker:** 100% containerized environment for consistent and dependency-free execution.
  - **Advanced Logs and Visualization:** Uses `tqdm` and `tabulate` to provide progress bars and clear, easy-to-read reports.

## The Bot's Philosophy

The decision-making of gcsBot follows a **3-layer intelligence hierarchy**, mimicking a military command structure to ensure robust and well-founded decisions:

### Layer 1: The General (Strategy)

- **Question:** "Is the battlefield favorable? Should we fight today?"
- **Action:** Analyzes the long-term **market regime** (`BULL_FORTE`, `BEAR`, etc.) using daily moving averages. Based on this scenario, it defines the general risk policy: whether trades are allowed and what the level of aggressiveness is. In a `BEAR` regime, the General may order a total withdrawal, preserving capital.

### Layer 2: The Captain (Tactic)

- **Question:** "Given that the General has given the green light, is this the exact moment to attack?"
- **Action:** The **Machine Learning model**, trained with recent data and aware of the market regime, looks for short-term patterns that indicate a high-probability buying opportunity. It generates a "buy confidence" signal.

### Layer 3: The Soldier (Execution and Management)

- **Question:** "Attack initiated. How do we manage this position to maximize gains and minimize losses?"
- **Action:** Once the purchase is executed, this module takes control with precise rules:
  1.  **Protection:** Moves the stop to _breakeven_ as soon as the trade reaches a small profit, eliminating the risk on the main capital.
  2.  **Realization:** Secures part of the profit by selling a fraction of the position when the profit target is reached.
  3.  **Maximization:** Lets the rest of the position "run" with a _trailing stop_ to capture larger trends.
  4.  **Treasury:** Allocates a portion of the realized profit to the "BTC Treasury", fulfilling the long-term accumulation objective.

This process transforms the bot from a simple signal executor into a strategic agent that thinks in multiple layers.

## The Bot's Ecosystem

- **`optimizer.py`**: The research brain. Manages the WFO, calls the `model_trainer` and `backtest`, and uses `Optuna` to find the best parameters for the complete strategy, optimizing for the Calmar Ratio.
- **`model_trainer.py`**: The "data scientist". Prepares all the features (technical, macro, and regime) and trains the LightGBM model so that it understands the market context.
- **`confidence_manager.py`**: The bot's "psychologist". Implements the logic to adjust confidence based on recent performance, making it more stable.
- **`backtest.py`**: The combat simulator. Executes the complete Multi-Layer strategy in a realistic way to provide the performance metrics (Drawdown, Return) for the optimizer.
- **`quick_tester.py`**: The "auditor". Allows validating an already trained model in a future time period, generating a complete report with the new performance metrics.
- **`trading_bot.py`**: The "elite pilot". Module that operates in the real market, implementing the same Multi-Layer strategy validated in the optimization.

## Quick Start Guide

Follow these steps to get the bot up and running.

### Prerequisites

- [Python 3.11+](https://www.python.org/downloads/)
- [Git](https://git-scm.com/downloads)
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (running)

### Installation

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/YOUR_USERNAME/gcsbot-btc.git
    cd gcsbot-btc
    ```
2.  **Run the Automatic Setup:**
    This command will check the environment, install the dependencies, and create your `.env` configuration file.

    ```bash
    python run.py setup
    ```

    > ⚠️ **Attention:** After the setup, open the newly created `.env` file and fill in **all** the variables, especially your API keys.

3.  **Build the Docker Image:**
    ```bash
    docker-compose build
    ```

## Environment Configuration

The `.env` file is the main control panel of the bot.

- **`MODE`**: Operating mode: `optimize`, `backtest`, `test`, or `trade`.
- **`FORCE_OFFLINE_MODE`**: `True` or `False`. Prevents the bot from accessing the internet (useful for optimizations).

#### API Keys

- `BINANCE_API_KEY` & `BINANCE_API_SECRET`: **Real** account keys.
- `BINANCE_TESTNET_API_KEY` & `BINANCE_TESTNET_API_SECRET`: **Testnet** account keys.

#### Portfolio Management (For `test` and `trade` modes)

- `MAX_USDT_ALLOCATION`: The **MAXIMUM** USDT capital that the bot is allowed to manage in its trading part.

## The Professional Workflow

The interaction with the bot is done through the `run.py` orchestrator. Follow these phases in the correct order.

### Phase Zero: Environment Cleanup (VERY IMPORTANT)

Before starting a **new** optimization for a reformulated strategy, it is essential to delete the old artifacts to ensure that the system starts from scratch, without any information from the previous strategy.

**Delete the following files from your `/data` directory:**

- `model.joblib`
- `scaler.joblib`
- `strategy_params.json`
- `wfo_optimization_state.json`
- `combined_data_cache.csv`

### Phase 1: Research and Optimization (`optimize`)

The most important step. The bot will study the entire history to find the best strategy and create the model files.

```bash
python run.py optimize
```

This process is long and can take hours or days. At the end, the `trading_model.pkl`, `scaler.pkl`, and `strategy_params.json` files will be saved in the `/data` folder.

---

### Phase 2: Quick Backtest

After optimization, validate the new strategy in a period that the model has never seen during training.

```bash
python run.py backtest --start "2024-01-01" --end "2025-01-01"
```

The bot will run the simulation and print a complete performance report, including the Calmar Ratio and the accumulated BTC Treasury.

---

### Phase 3: Testnet Validation

If the validation is positive, test the strategy in the live market with test money.

```bash
python run.py test
```

It will use the model and parameters created in Phase 1. Let it run for at least 1-2 weeks to observe the behavior in real time.

---

### Phase 4: Real Trading

The final step. The bot will operate in the same way as in test mode, but using your real Binance account and your defined capital allocation.

```bash
python run.py trade
```

---

## Additional Commands

- View Logs in Real Time:

```bash
python run.py logs
```

- Stop the Bot (`test` or `trade` mode):

```bash
python run.py stop
```

---

## Project Structure

```bash
gcsbot-btc/
├── data/                  # Generated data (CSVs, models, states) - Ignored by Git
├── logs/                  # Daily log files - Ignored by Git
├── src/                   # Project source code
│   ├── __init__.py
│   ├── backtest.py        # Realistic simulation engine (used by optimization)
│   ├── config.py          # Configuration manager for .env
│   ├── confidence_manager.py # Adaptive confidence brain
│   ├── data_manager.py    # Data collection and caching manager
│   ├── logger.py          # Log system configuration
│   ├── model_trainer.py   # Prepares features and trains the ML model
│   ├── optimizer.py       # Walk-Forward Optimization (WFO) orchestrator
│   ├── quick_tester.py    # Logic for the quick backtest mode (validation)
│   └── trading_bot.py     # Real operation and portfolio management logic
├── .dockerignore          # Files to be ignored by Docker
├── .env.example           # Example of the configuration file
├── .gitignore             # Files to be ignored by Git
├── Dockerfile             # Defines the Docker environment for the bot
├── main.py                # Main entry point (used by Docker)
├── README.md              # This documentation
├── requirements.txt       # Python dependencies
└── run.py                 # Main orchestrator and user entry point
```

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
