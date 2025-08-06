# GCS-Bot: A Sophisticated Cryptocurrency Trading Bot

GCS-Bot is a powerful, event-driven cryptocurrency trading bot designed for adaptability and transparency. It leverages a sophisticated grid-DCA strategy, real-time feature calculation, and a comprehensive monitoring dashboard to trade on the Binance exchange.

## Core Philosophy

*   **Discipline:** The system executes its rules without emotion or deviation. All logic for entry, management, and exit is absolute and auditable.
*   **Adaptation:** The market is a living organism. Our bot is not a rigid statue; it adapts its strategy based on market regimes.
*   **Robustness:** The system is a battle tank. Built on the principles of Defensive Software Engineering, it anticipates and handles real-world imperfections—missing data, API errors, network latency—without ever failing its core mission.
*   **Transparency:** The bot is not a "black box." Using the new dashboard, we have a clear window into the bot's real-time operations, account status, and performance.

## Features

*   **Advanced Trading Strategy:** Implements a hybrid Grid-DCA (Dollar-Cost Averaging) strategy.
*   **Partial Sells:** Takes profit on 90% of a position, leaving the remaining 10% to run, maximizing profit potential.
*   **Live Monitoring Dashboard:** A comprehensive, real-time terminal dashboard to monitor performance, balances, and trades.
*   **Binance Integration:** Connects to Binance for live trading, testnet trading, and account data.
*   **Multiple Operating Modes:** Supports `trade` (live), `test` (testnet), `backtest`, and `offline` modes.
*   **Dockerized Environment:** Ensures a consistent and reliable operating environment.

## Getting Started

### Prerequisites

*   [Docker Desktop](https://www.docker.com/products/docker-desktop/) (must be running)
*   [Python 3.10+](https://www.python.org/downloads/)

### 1. Installation

First, clone the repository to your local machine:
```bash
git clone https://github.com/your-username/gcs-bot.git
cd gcs-bot
```

### 2. Configuration

The bot uses two primary configuration files: `.env` for secrets and `config.yml` for strategy parameters.

**a. Environment Variables (`.env`)**

Create a `.env` file by copying the example file:
```bash
cp .env.example .env
```
Now, open the `.env` file and fill in your Binance API keys. You will need separate keys for the mainnet and the testnet.

**b. Strategy Configuration (`config.yml`)**

The `config.yml` file contains all the parameters for the trading strategy, backtesting, and other settings. You can modify this file to customize the bot's behavior.

### 3. Setup the Environment

Run the setup command to build the Docker images and start the necessary services (like the InfluxDB database):
```bash
python3 run.py setup
```

## Usage

All commands are executed through the `run.py` script:
```bash
python3 run.py [command]
```

### Environment Management
*   `setup`: Builds and starts the Docker environment for the first time.
*   `start-services`: Starts the Docker containers (app, db).
*   `stop-services`: Stops the Docker containers.
*   `reset-db`: **DANGER!** Stops and erases the database.

### Bot Operations
*   `trade`: Starts the bot in **live trading mode** (real money).
*   `test`: Starts the bot in **test mode** (live data on Binance Testnet).
*   `backtest`: Runs a backtest using the current models and historical data.
*   `optimize`: Runs the model optimization process.
*   `update-db`: Runs the ETL pipeline to populate/update the database with market data.

### Database Utilities
*   `clean-master`: Clears the `features_master_table`.
*   `reset-trades`: Clears all trade records from the database.
*   `reset-sentiment`: Clears all sentiment data from the database.

### Monitoring & Analysis
*   `show-trading`: Shows the live trading dashboard.
*   `show-optimizer`: Shows the optimizer dashboard.
*   `logs`: Shows the raw logs from the running application.
*   `analyze`: Analyzes the results of the last backtest run.
*   `analyze-decision <model> "<datetime>"`: Analyzes a specific model's decision.
*   `run-tests`: Runs the automated test suite (pytest).

## Execution Modes

*   **`trade`**: Live trading on the Binance mainnet with real funds. Use with caution.
*   **`test`**: Live trading on the Binance Testnet. Uses real-time market data but places orders on the testnet, so no real funds are at risk. This is the recommended mode for testing new strategies.
*   **`backtest`**: Simulates the trading strategy on historical data. Useful for evaluating the performance of a strategy over a long period.
*   **`offline`**: A mode for development and testing without an internet connection. The bot will not connect to Binance.

## Trading Strategy

The bot employs a hybrid strategy that combines elements of Dollar-Cost Averaging (DCA) and grid trading, with a unique take-profit mechanism.

*   **Entry Logic:**
    *   **Dip Buying:** The primary entry signal is a dip in price.
    *   **Uptrend Entry:** To avoid missing out on strong uptrends, the bot will also enter a position after a configurable number of consecutive green candles.
*   **Exit Logic:**
    *   **Partial Take-Profit:** When a position becomes profitable, the bot sells 90% of the position to lock in gains. The remaining 10% is left to run, potentially capturing further upside.
    *   **Stop-Loss:** Each trade has a stop-loss calculated based on the Average True Range (ATR) at the time of entry.

## Trading Dashboard

The trading dashboard provides a real-time overview of the bot's performance and status. To view it, run `python3 run.py show_trading` while the bot is running in `trade` or `test` mode.

The dashboard includes:
*   **Portfolio:** Your current BTC and USDT balances, and the total value of your portfolio.
*   **Session Stats:** Total realized Profit & Loss, and counts of open and closed trades.
*   **Bot's Internal Trades:** A summary of the last few trades as recorded by the bot.
*   **Binance Open Orders:** A list of open orders for the trading symbol, fetched directly from Binance.
*   **Binance Trade History:** Your recent trade history for the symbol, fetched directly from Binance for verification.

## Architecture

The project is organized into a clean, professional, and scalable structure.
*   **`run.py`**: The main command-line interface (CLI).
*   **`gcs_bot/`**: The main Python package.
    *   **`core/`**: The bot's brain, containing the logic for trading, position management, and exchange interaction.
    *   **`database/`**: Manages all interactions with the InfluxDB database.
    *   **`utils/`**: Shared utilities for configuration and logging.
