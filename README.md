# GCS Trading Bot

A sophisticated, data-driven automated trading bot for the BTC/USDT market.

## Table of Contents
- [Overview](#1-overview)
- [Features](#2-features)
- [Architecture](#3-architecture)
- [Project Structure](#4-project-structure)
- [Setup and Installation](#5-setup-and-installation)
- [CLI Commands](#6-cli-commands)
- [Database Schema](#7-database-schema)
- [Key Calculations](#8-key-calculations)

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
  - A `postgres_setup/init.sql` script initializes the entire PostgreSQL environment, creating the necessary schemas and roles.
  - A lean price collector (`collectors/core_price_collector.py`) automatically ingests and stores all required price data in a PostgreSQL time-series database.
- **Situational Awareness Model**: Utilizes a K-Means clustering model to classify the market into one of several "regimes" (e.g., Bull Volatile, Bear Quiet), allowing the strategy to adapt to changing conditions. The code for this is in the `research` directory.
- **Dockerized Environment**: The entire application stack, including the Python application and the PostgreSQL database, is managed by Docker and Docker Compose for easy setup and deployment.
- **Command-Line Interface**: A central script `run.py` provides a simple interface for managing the entire lifecycle of the bot and its environment.
- **Interactive Terminal UI (TUI)**: A sophisticated, real-time dashboard built with Textual that connects to a dedicated API service. It provides live updates on per-position unrealized PnL, progress towards buy/sell targets, and live wallet balances.
- **Live Data Synchronization**: The bot's status service actively reconciles its internal database state with live open orders from the Binance exchange, ensuring the UI always displays an accurate view of your real positions.
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
| PositionManager| |   AccountManager    | |     PostgresManager      |
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
  - `postgres`: The PostgreSQL container for data storage.
  - `pgadmin`: A web-based administration tool for PostgreSQL.
  - `app`: The Python application container where the bot logic runs.
- **`jules_bot/main.py`**: The main function inside the `app` container. It reads the `BOT_MODE` environment variable and instantiates the `TradingBot`.
- **`TradingBot`**: The central orchestrator. It initializes all the necessary manager classes and runs the main trading loop (for live/test) or the backtesting process.
- **`PositionManager`**: Contains the core trading strategy logic. It decides when to buy or sell based on the data from the database.
- **`AccountManager` / `SimulatedAccountManager`**: Handles the execution of trades.
  - `AccountManager`: Interacts with the live or testnet exchange via the `ExchangeManager`. It validates and formats orders before placing them.
  - `SimulatedAccountManager`: Simulates an exchange account for backtesting, tracking balances locally without making real API calls.
- **`ExchangeManager`**: A low-level wrapper around the `python-binance` client. It handles all direct communication with the Binance API (e.g., fetching prices, placing orders).
- **`PostgresManager`**: Abstracts the database. It provides methods to read and write to PostgreSQL using SQLAlchemy.

## 4. Project Structure

The repository is organized into several key directories:

```
gcsbot-btc/
├── .dvc/                   # Data Version Control (for large data files)
├── collectors/             # Scripts for collecting data
├── config/                 # Configuration files for services (e.g., postgres.conf)
├── data/                   # Local data storage (e.g., historical CSVs, models)
├── postgres_setup/         # Scripts for automated PostgreSQL initialization
│   └── init.sql
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

## 5. Setup and Installation

This guide provides the step-by-step instructions to set up the environment and run the bot.

### Prerequisites

- **Docker and Docker Compose**: Ensure Docker is installed and running.
- **Python 3.10+**: Required for running the control script `run.py`.
- **Git**: For cloning the repository.

### Step 1: Clone and Configure

First, clone the repository and create your `.env` file from the example.

```bash
git clone <YOUR_REPOSITORY_URL>
cd gcsbot-btc
cp .env.example .env
```

Next, edit the `.env` file with your details. You will need to provide your Binance API keys. The PostgreSQL credentials are set in `docker-compose.yml` and `config/postgres.conf`.

### Step 2: Start the Environment

The `start` command builds the Docker images and launches the `app`, `postgres`, and `pgadmin` services in the background. The `app` container will start in an idle state, waiting for your commands.

```bash
python run.py start
```

## 6. CLI Commands

All interaction with the bot and its environment is handled through `run.py`.

### Environment Management

These commands control the Docker environment.

| Command | Description |
|---|---|
| `start` | Builds and starts all services (`app`, `postgres`, `pgadmin`) in detached mode. |
| `stop` | Stops and removes all services and associated volumes. |
| `status` | Shows the current status of all running services. |
| `build` | Forces a rebuild of the Docker images without starting them. Useful after changing the `Dockerfile`. |
| `logs [service]` | Tails the logs of a specific service (e.g., `app`, `db`) or all services if none is specified. |

### Application Control

These commands execute tasks inside the `app` container.

#### Running the Bot

The bot can be run in `live` or `test` mode. These commands will start the trading logic, and you can follow the bot's activity through its logs.

- **Live Trading**: `python run.py trade`
- **Paper Trading (Testnet)**: `python run.py test`

While the bot is running, you can use the `dashboard` command in a separate terminal to monitor it.

#### Monitoring with the Dashboard

The primary way to monitor the bot is through the interactive TUI. The `dashboard` command is the easiest way to get started, as it launches both the necessary API service and the UI.

- **To monitor the Testnet bot:**
  ```bash
  python run.py dashboard --mode test
  ```

- **To monitor the Live bot:**
  ```bash
  python run.py dashboard --mode trade
  ```

Alternatively, you can use the new **local TUI**, which runs the bot and the UI in the same process, eliminating the need for a separate API service. This is the recommended approach for most users.

- **To run the local TUI for the Testnet bot:**
  ```bash
  python run.py ui-local --mode test
  ```

| Command | Description |
|---|---|
| `trade` | Starts the bot in **live trading mode** using your main Binance account. |
| `test` | Starts the bot in **paper trading mode** using your Binance testnet account. |
| `ui-local` | Starts the new **local TUI** which runs the bot and UI in a single process. Recommended for monitoring. |
| `dashboard` | (Legacy) Starts the API and the interactive TUI for live monitoring. Use `--mode` to specify `trade` or `test`. |
| `backtest` | Prepares historical data and runs a full backtest. Use the `--days` option (e.g., `--days 30`) to specify the period. |
| `api` | (Legacy) Starts the API service independently. Use `--mode` to specify `trade` or `test`. |
| `ui` | (Legacy) Starts the WebSocket-based TUI. Requires the API to be running separately. |
| `clear-backtest-trades` | **Deletes all trades** from the `backtest` environment in the database. Useful for starting a fresh backtest analysis. |


## 7. Database Schema

The application uses a PostgreSQL database to store all persistent data. The schema is defined in `jules_bot/database/models.py` and consists of three main tables.

### `price_history`

Stores historical OHLCV (Open, High, Low, Close, Volume) price data for assets.

| Column | Type | Description |
|---|---|---|
| `id` | Integer | Primary key. |
| `timestamp` | DateTime | The timestamp for the start of the candle (e.g., minute). |
| `open` | Float | The opening price for the period. |
| `high` | Float | The highest price for the period. |
| `low` | Float | The lowest price for the period. |
| `close` | Float | The closing price for the period. |
| `volume` | Float | The trading volume for the period. |
| `symbol` | String | The trading symbol (e.g., 'BTCUSDT'). |

### `trades`

The central table for recording all trading activity. A single row represents the entire lifecycle of a trade, from buy to sell.

| Column | Type | Description |
|---|---|---|
| `id` | Integer | Primary key. |
| `run_id` | String | The unique ID for the bot session that initiated the trade. |
| `environment` | String | The environment the trade was made in ('trade', 'test', or 'backtest'). |
| `strategy_name`| String | The name of the strategy that triggered the trade. |
| `symbol` | String | The trading symbol (e.g., 'BTCUSDT'). |
| `trade_id` | String | A unique identifier for the trade lifecycle. |
| `exchange` | String | The exchange where the trade occurred (e.g., 'binance'). |
| `status` | String | The current status of the trade: 'OPEN' or 'CLOSED'. |
| `order_type` | String | The type of order that opened the position. Always 'buy'. |
| `price` | Float | The price of the transaction. For an open trade, this is the buy price. For a closed trade, this is the sell price. |
| `quantity` | Float | The amount of the asset traded. |
| `usd_value` | Float | The total value of the transaction in USD. |
| `commission` | Float | The commission paid for the transaction. |
| `commission_asset` | String | The asset the commission was paid in (e.g., 'USDT'). |
| `timestamp` | DateTime | The timestamp of the transaction. Updated to the sell time when a trade is closed. |
| `exchange_order_id`| String | The order ID provided by the exchange. |
| `decision_context`| JSON | A JSON object containing the market data and indicators at the time the decision was made. |
| `sell_target_price`| Float | The target price at which to sell, calculated at buy time. |
| `commission_usd` | Float | The total commission for the sell part of the trade, in USD. |
| `realized_pnl_usd`| Float | The realized profit or loss from the trade in USD, calculated upon selling. |
| `hodl_asset_amount`| Float | The amount of the asset held back from the sell (if not selling 100%). |
| `hodl_asset_value_at_sell`| Float | The USD value of the `hodl_asset_amount` at the time of the sell. |

### `bot_status`

A simple table for storing the last known state of a running bot instance, used primarily by the UI.

| Column | Type | Description |
|---|---|---|
| `id` | Integer | Primary key. |
| `bot_id` | String | The unique ID of the bot session. |
| `mode` | String | The mode the bot is running in ('trade' or 'test'). |
| `is_running` | Boolean | Whether the bot is currently running. |
| `session_pnl_usd`| Float | The profit or loss for the current session. |
| `session_pnl_percent`| Float | The profit or loss for the current session, as a percentage. |
| `open_positions` | Integer | The number of currently open positions. |
| `portfolio_value_usd`| Float | The total current value of the portfolio. |
| `timestamp` | DateTime | The last time the status was updated. |

## 8. Key Calculations

### Realized Profit & Loss (PnL)

The realized PnL for a trade is calculated when a position is sold. The formula, found in `jules_bot/backtesting/engine.py`, accounts for commission fees on both the buy and sell transactions to provide an accurate reflection of the net profit.

**Formula:**
```
realized_pnl_usd = ((sell_price * (1 - commission_rate)) - (buy_price * (1 + commission_rate))) * quantity_sold
```

- `sell_price`: The price at which the asset was sold.
- `buy_price`: The price at which the asset was originally purchased.
- `commission_rate`: The percentage fee charged by the exchange (e.g., 0.001 for 0.1%).
- `quantity_sold`: The amount of the asset that was sold.

This formula ensures that the profit is only calculated on the capital that was returned after fees were deducted on both ends of the trade lifecycle.

## 9. Terminal User Interface (TUI)

The bot includes a powerful, real-time Terminal User Interface (TUI) for monitoring and manual control, launched with the `run.py dashboard` command.

### TUI Preview

```
+------------------------------------------------------------------------------------------------+
| Jules Bot        Last Update: 2023-10-27 10:30:00                                              |
+------------------------------------------------------------------------------------------------+
| Left Pane (Bot Control & Logs)      | Right Pane (Status & Positions)                          |
|                                     |                                                          |
| Bot Control                         | Bot Status                                               |
| Manual Buy (USD): [ 100.00 ]        | Mode: TEST   Symbol: BTC/USDT   Price: $34,123.45         |
| [ FORCE BUY ]                       |                                                          |
|                                     | Strategy                                                 |
| Live Log                            | Buy Signal: Uptrend pullback                             |
| > UI: Sent command...               | Buy Target: $34,050.00   Progress: 75.5%                 |
| > Bot: Sell condition met...        |                                                          |
|                                     | Open Positions                                           |
|                                     | ID   | Entry   | Qty    | Value   | PnL     | Sell Target | Progress |
|                                     |------|---------|--------|---------|---------|-------------|----------|
|                                     | ab12 | 34000.0 | 0.01   | $341.23 | +$1.23  | $34500.00   | 24.6%    |
|                                     | cd34 | 33950.0 | 0.02   | $682.46 | +$3.46  | $34400.00   | 38.8%    |
|                                     |                                                          |
|                                     | [ Force Sell ] [ Mark as Treasury ]                      |
+------------------------------------------------------------------------------------------------+
```

### Key UI Features

- **Live Status**: Real-time updates on the bot's mode, the current asset price, and buy signal status.
- **Bot Control**: A panel to manually trigger a buy order for a specific USD amount.
- **Live Log**: A stream of the latest log messages from the bot.
- **Open Positions Table**: A detailed list of all open trades, including:
  - **Unrealized PnL**: The current profit or loss for each position.
  - **Sell Target & Progress**: The target price for selling and how close the current price is to reaching it.
- **Manual Intervention**: Select a trade in the table to bring up options to **Force Sell** it or mark it as **Treasury** (a long-term hold).
