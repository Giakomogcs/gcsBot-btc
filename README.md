# GCS Trading Bot

## 1. Overview

GCS Trading Bot is a sophisticated, data-driven automated trading bot designed for the BTC/USDT market on the Binance exchange. It leverages a robust data pipeline, machine learning for market regime detection, and a flexible architecture to support live trading, paper trading (testnet), and comprehensive backtesting.

The system is fully containerized using Docker, ensuring a consistent and reproducible environment for both development and production. It is controlled via a simple yet powerful command-line interface (`run.py`) that manages everything from starting services to running data pipelines and executing trades.

## 2. Features

- **Multiple Execution Modes**:
  - **Live Trading**: Execute trades with real capital on the Binance spot market.
  - **Paper Trading**: Trade on the Binance testnet without risking real funds.
  - **Backtesting**: Simulate trading strategies on historical data to evaluate performance.
- **Data-Driven Strategy**: Decisions are not based on simple rules but on a rich dataset including:
  - OHLCV price data
  - Technical indicators (RSI, MACD, Bollinger Bands, etc.)
  - Order flow data (Taker Buy/Sell Volume)
  - Market sentiment (Fear & Greed Index)
  - Macroeconomic data (DXY, VIX, Gold, etc.)
- **Automated Setup & Data Pipeline**:
  - A one-time setup script (`influxdb_setup/run_migrations.py`) initializes the entire InfluxDB environment, creating the organization, buckets, and application token.
  - A lean price collector (`collectors/core_price_collector.py`) automatically ingests and stores all required price data in an InfluxDB time-series database.
- **Situational Awareness Model**: Utilizes a K-Means clustering model to classify the market into one of several "regimes" (e.g., Bull Volatile, Bear Quiet), allowing the strategy to adapt to changing conditions. The code for this is in the `research` directory.
- **Dockerized Environment**: The entire application stack, including the Python application and the InfluxDB database, is managed by Docker and Docker Compose for easy setup and deployment.
- **Command-Line Interface**: A central script `run.py` provides a simple interface for managing the entire lifecycle of the bot and its environment.
- **Interactive Terminal UI (TUI)**: A sophisticated, real-time dashboard built with Textual that allows you to monitor bot status, view portfolio performance (including unrealized PnL), and intervene manually by forcing buys or sells.
- **Resilient and Modular Architecture**: The code is organized into decoupled components (bot logic, database management, exchange connection), making it easier to maintain and extend.

## 3. Architecture

The bot is designed with a modular architecture, separating concerns to improve maintainability and testability.

```
+-------------------+      +----------------------+      +--------------------+
|     run.py        |----->| docker-compose.yml   |----->|   jules_bot/main.py  |
| (User Interface)  |      | (Service Definition) |      | (App Entry Point)  |
+-------------------+      +----------------------+      +--------------------+
                                                            |
                                                            V
+---------------------------------------------------------------------------------+
|                                  TradingBot (`trading_bot.py`)                  |
|                                     (Orchestrator)                              |
|---------------------------------------------------------------------------------|
| - Initializes all managers based on BOT_MODE (trade, test, backtest)            |
| - Runs the main trading loop or the backtest process.                           |
+---------------------------------------------------------------------------------+
      |                 |                  |
      V                 V                  V
+----------------+ +---------------------+ +--------------------------+
| PositionManager| |   AccountManager    | |     DatabaseManager      |
| (Strategy)     | |     (Execution)     | |     (Persistence)        |
+----------------+ +---------------------+ +--------------------------+
      |                 |                     |
      |                 V                     |
      |       +-------------------+           |
      +------>| ExchangeManager   |<----------+
              | (API Connector)   |
              +-------------------+

```

- **`run.py` (CLI)**: The main entry point for the user. It parses user commands and executes the appropriate `docker-compose` commands to build, start, stop, and interact with the application.
- **`docker-compose.yml`**: Defines the services that make up the application:
  - `db`: The InfluxDB container for data storage.
  - `app`: The Python application container where the bot logic runs.
- **`jules_bot/main.py`**: The main function inside the `app` container. It reads the `BOT_MODE` environment variable and instantiates the `TradingBot`.
- **`TradingBot`**: The central orchestrator. It initializes all the necessary manager classes and runs the main trading loop (for live/test) or the backtesting process.
- **`PositionManager`**: Contains the core trading strategy logic. It decides when to buy or sell based on the data from the database.
- **`AccountManager` / `SimulatedAccountManager`**: Handles the execution of trades.
  - `AccountManager`: Interacts with the live or testnet exchange via the `ExchangeManager`. It validates and formats orders before placing them.
  - `SimulatedAccountManager`: Simulates an exchange account for backtesting, tracking balances locally without making real API calls.
- **`ExchangeManager`**: A low-level wrapper around the `python-binance` client. It handles all direct communication with the Binance API (e.g., fetching prices, placing orders).
- **`DatabaseManager` / `DataManager`**: Abstract the database.
  - `DatabaseManager`: Provides generic methods to read and write to InfluxDB.
  - `DataManager`: Provides a higher-level API to access specific, curated datasets like the `features_master_table`.

## 4. Project Structure

The repository is organized into several key directories:

```
gcsbot-btc/
├── .dvc/                   # Data Version Control (for large data files)
├── collectors/             # Scripts for collecting data
├── config/                 # Configuration files for services (e.g., influxdb.conf)
├── data/                   # Local data storage (e.g., historical CSVs, models)
├── influxdb_setup/         # Scripts for automated InfluxDB initialization
│   ├── migrations/
│   └── run_migrations.py
├── jules_bot/              # Main Python source code for the bot application
│   ├── bot/                # Core trading logic and position management
│   ├── core/               # Core components like schemas and connectors
│   ├── database/           # Database interaction and data management
│   └── utils/              # Utility modules like logging and configuration
├── logs/                   # Log files and trading status JSONs
├── research/               # Scripts for research and feature engineering
├── scripts/                # Standalone Python scripts for automation and analysis
├── tests/                  # Automated tests for the application
├── .env.example            # Example environment variables file
├── config.ini              # Main application configuration file
├── docker-compose.yml      # Docker service definitions
├── Dockerfile              # Docker image definition for the application
└── run.py                  # Main command-line interface for controlling the bot
```

## 5. Usage Guide

This guide provides the step-by-step instructions to set up the environment and run the bot.

### Prerequisites

- **Docker and Docker Compose**: Ensure Docker is installed and running. The script will automatically use `sudo` if required.
- **Python 3.10+**: Required for running the control script `run.py`.
- **Git**: For cloning the repository.

### Step 1: Clone and Configure

First, clone the repository and create your `.env` file from the example.

```bash
git clone <YOUR_REPOSITORY_URL>
cd gcsbot-btc
cp .env.example .env
```

Next, edit the `.env` file with your details. You will need to provide your Binance API keys and choose names for your InfluxDB organization and buckets.

### Step 2: Start the Environment

The `start` command builds the Docker images and launches the `app` and `db` services in the background. The `app` container will start in an idle state, waiting for your commands.

```bash
python run.py start
```

You can check the status of the services at any time:

```bash
python run.py status
```

### Step 3: Initial Database Setup

The first time you run the bot, you need to set up the InfluxDB database. The following command runs a one-time migration script that creates the necessary buckets and tokens.

```bash
python influxdb_setup/run_migrations.py
```

This script will output a new `INFLUXDB_TOKEN`. **You must copy this token and paste it into your `.env` file.**

### Step 4: Running the Bot

With the environment running and the database configured, you can now execute commands inside the application container.

**A. Run a Backtest**
To run a backtest, you first need to collect some historical data. The `backtest` command handles this for you.

```bash
# Prepare data for the last 30 days and run a backtest
python run.py backtest --days 30
```

This command will:

1.  Execute a script inside the container to fetch the last 30 days of price data.
2.  Execute the backtesting engine using that data.

**B. Run in Test Mode (Testnet)**
To run the bot using your Binance testnet account:

```bash
python run.py test
```

The bot will start, and you will see its log output directly in your terminal. Press `Ctrl+C` to stop the bot.

**C. Run in Live Trading Mode**
To run the bot with real funds on your main Binance account:

```bash
python run.py trade
```

The bot will start, and its logs will be streamed to your terminal. Press `Ctrl+C` to stop it.

**D. Using the Interactive Terminal UI (TUI)**
The bot includes a powerful, real-time Terminal User Interface (TUI) for monitoring and manual control.

To use the TUI, you must have the bot running in either `test` or `trade` mode in one terminal. Then, in a **second terminal**, run:

```bash
python run.py ui
```

This will launch the dashboard, which provides:

- **Live Status & Portfolio**: Real-time updates on the bot's mode, the current asset price, total investment, current portfolio value, and unrealized Profit & Loss (PnL).
- **Bot Control**: A panel to manually trigger a buy order for a specific USD amount.
- **Live Log**: A stream of the latest log messages from the bot.
- **Open Positions Table**: A detailed list of all open trades, including entry price, quantity, and current value.
- **Manual Intervention**: Select a trade in the table to bring up options to **Force Sell** it or mark it as **Treasury** (a long-term hold).

A preview of the TUI layout:

```
+-----------------------------------------------------------------------------+
| Jules Bot        Last Update: 2023-10-27 10:30:00                           |
+-----------------------------------------------------------------------------+
| Left Pane (Bot Control & Logs)      | Right Pane (Status & Positions)       |
|                                     |                                       |
| Bot Control                         | Bot Status                            |
| Manual Buy (USD): [ 100.00 ]        | Mode: TEST   Symbol: BTCUSDT          |
| [ FORCE BUY ]                       | Price: $34,123.45                     |
|                                     |                                       |
| Live Log                            | Portfolio                             |
| > UI: Sent command...               | Invested: $5,000  Value: $5,150       |
| > Bot: Sell condition met...        | PnL: +$150.00                         |
|                                     |                                       |
|                                     | Open Positions                        |
|                                     | ID   | Entry   | Qty    | Value       |
|                                     |------|---------|--------|------------ |
|                                     | ab12 | 34000.0 | 0.01   | $341.23     |
|                                     | cd34 | 33950.0 | 0.02   | $682.46     |
|                                     |                                       |
|                                     | [ Force Sell ] [ Mark as Treasury ]   |
+-----------------------------------------------------------------------------+
```

### Step 5: Managing the Environment

- **View Logs**: To see the real-time logs from any service (e.g., `app` or `db`):
  ```bash
  python run.py logs <service_name>
  # Example:
  python run.py logs app
  ```
- **Stop Services**: To stop all services and remove the containers:
  ```bash
  python run.py stop
  ```
- **Rebuild Images**: If you make changes to the `Dockerfile`, you can force a rebuild:
  ```bash
  python run.py build
  ```
