# GCS Trading Bot

A sophisticated, data-driven automated trading bot for the BTC/USDT market.

## Table of Contents
- [Overview](#1-overview)
- [Features](#2-features)
- [Architecture](#3-architecture)
- [Project Structure](#4-project-structure)
- [Setup and Installation](#5-setup-and-installation)
- [How to Use the Bot](#6-how-to-use-the-bot)
- [Database Schema](#7-database-schema)

## 1. Overview

GCS Trading Bot is a sophisticated, data-driven automated trading bot designed for the BTC/USDT market on the Binance exchange. It leverages a robust data pipeline, machine learning for market regime detection, and a flexible architecture to support live trading, paper trading (testnet), and comprehensive backtesting.

The system is fully containerized using Docker, ensuring a consistent and reproducible environment. Interaction with the bot is handled through a streamlined command-line interface (`run.py`), a powerful real-time dashboard (TUI), and a set of direct control scripts.

## 2. Features

- **Multiple Execution Modes**:
  - **Live Trading**: Execute trades with real capital on the Binance spot market.
  - **Paper Trading**: Trade on the Binance testnet without risking real funds.
  - **Backtesting**: Simulate trading strategies on historical data to evaluate performance.
- **Script-Based Control**: The bot is controlled by a set of powerful, fast, and reliable command-line scripts, giving you direct control without needing a web server.
- **Interactive Dashboard (TUI)**: A new, high-performance Terminal User Interface provides a real-time view of the bot's status, open positions, wallet balances, and live logs.
- **Data-Driven Strategy**: Decisions are based on a rich dataset including OHLCV, technical indicators, order flow, market sentiment, and macroeconomic data.
- **Automated Data Pipeline**: A `postgres_setup/init.sql` script initializes the database, and the bot's own `LiveFeatureCalculator` continuously fetches and processes the required data.
- **Dockerized Environment**: The entire application stack (Python app, PostgreSQL DB) is managed by Docker Compose for easy setup and deployment.

## 3. Architecture

The bot's architecture is designed for simplicity and robustness, centered around a main bot process that can be monitored and controlled via local scripts and a terminal dashboard.

```
+-------------------+      +----------------------+      +--------------------+
|      run.py       |----->| docker-compose.yml   |----->|  jules_bot/main.py   |
| (Control Script)  |      | (Service Definition) |      |  (Bot Entry Point) |
+-------------------+      +----------------------+      +--------------------+
        ^                                                       |
        |                                                       V
+-------------------+      +--------------------+      +----------------------+
|  scripts/*.py     |<---->|     commands/      |<---->|  TradingBot          |
| (Manual Commands) |      |   (File-based      |      |  (Orchestrator)      |
+-------------------+      |      Queue)        |      +----------------------+
        ^                  +--------------------+
        |
+-------------------+
|  tui/app.py       |
| (Dashboard)       |
+-------------------+
```

- **`run.py` (CLI)**: The main entry point for managing the bot's lifecycle (starting, stopping, running).
- **`jules_bot/main.py`**: The entry point inside the container; it instantiates and starts the `TradingBot`.
- **`TradingBot`**: The central orchestrator. It runs the main trading loop and continuously checks the `commands/` directory for manual instructions.
- **`scripts/`**: A folder containing standalone Python scripts for direct interaction:
  - `get_bot_data.py`: Fetches a complete status snapshot of the bot.
  - `force_buy.py` & `force_sell.py`: Create command files in the `commands/` directory to manually trigger trades.
- **`tui/app.py`**: A Textual application that provides a dashboard view. It calls the scripts to get data and issue commands.

## 4. Project Structure

The repository is organized for clarity and separation of concerns.

```
gcsbot-btc/
├── jules_bot/              # Main Python source code
│   ├── bot/                # Core trading logic
│   ├── core/               # Core components (connectors, schemas)
│   ├── database/           # Database interaction
│   └── utils/              # Utility modules (logging, config)
├── logs/                   # Structured JSON log files
├── scripts/                # Standalone Python scripts for automation and control
├── tui/                    # Source for the new Terminal User Interface
├── ... (other config folders)
└── run.py                  # Main command-line interface
```

## 5. Setup and Installation

### Prerequisites
- Docker and Docker Compose
- Python 3.10+
- Git

### Step 1: Clone and Configure
```bash
git clone <YOUR_REPOSITORY_URL>
cd gcsbot-btc
cp .env.example .env
```
Next, edit the `.env` file with your Binance API keys.

### Step 2: Start the Environment
This command builds the Docker images and starts the `app` and `postgres` services.
```bash
python run.py start
```

## 6. How to Use the Bot

### Running the Bot
To start the bot, use the `trade` or `test` commands. This will run the main bot loop in the container. You should run this in one terminal window.
- **Live Trading**: `python run.py trade`
- **Paper Trading (Testnet)**: `python run.py test`

### Monitoring with the Dashboard
To monitor a running bot, open a **second terminal window** and use the `dashboard` command.
- **To monitor the Testnet bot**: `python run.py dashboard --mode test`
- **To monitor the Live bot**: `python run.py dashboard --mode trade`

The dashboard provides a real-time view of open positions, wallet balances, and live logs. You can also trigger manual trades from the dashboard.

### Direct Script-Based Control
For automation or direct control, you can use the scripts in the `scripts/` folder.

| Command | Description |
|---|---|
| `python scripts/get_bot_data.py <mode>` | Dumps a full JSON report of the bot's status. `<mode>` can be `trade` or `test`. |
| `python scripts/force_buy.py <amount>` | Commands the bot to buy a specific USD amount of crypto. |
| `python scripts/force_sell.py <id> <pct>`| Commands the bot to sell a percentage of an open trade. Example: `... force_sell.py <trade_id> 90`. |

### Other `run.py` Commands

| Command | Description |
|---|---|
| `start` | Builds and starts all services in detached mode. |
| `stop` | Stops and removes all services and volumes. |
| `status` | Shows the status of running services. |
| `build` | Forces a rebuild of the Docker images. |
| `logs [service]` | Tails the logs of a service. |
| `backtest` | Runs a full backtest. |
| `clear-testnet-trades`| Deletes all test trades from the database. |

## 7. Database Schema
The application uses a PostgreSQL database to store all persistent data, including `price_history` and `trades`. The schema is defined in `jules_bot/database/models.py`. The `bot_status` table is no longer actively used by the new TUI.
