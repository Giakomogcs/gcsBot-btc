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
- **Interactive Terminal UI (TUI)**: A new, high-performance dashboard built with Textual that provides a real-time view of the bot's status, open positions, wallet balances, and live logs.
- **Script-Based Control**: The bot is controlled by a set of powerful, fast, and reliable command-line scripts, giving you direct control without needing a web server.
- **Resilient and Modular Architecture**: The code is organized into decoupled components (bot logic, database management, exchange connection), making it easier to maintain and extend.

## 3. Architecture

The bot's architecture is now centered around a main bot process that can be monitored and controlled via local scripts and a terminal dashboard, removing the need for a web API.

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

The repository is organized into several key directories:

```
gcsbot-btc/
├── jules_bot/              # Main Python source code for the bot application
│   ├── bot/                # Core trading logic and position management
│   ├── core/               # Core components (connectors, schemas)
│   ├── database/           # Database interaction
│   └── utils/              # Utility modules like logging and configuration
├── logs/                   # Structured JSON log files
├── scripts/                # Standalone Python scripts for automation and control
├── tui/                    # Source for the new Terminal User Interface
├── ... (other config folders)
└── run.py                  # Main command-line interface
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

> **Important**: If you change the `.env` file after the application has been started, you must restart the Docker services for the changes to take effect. You can do this by running `python run.py stop` followed by `python run.py start`.

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

The application is controlled via a combination of the main `run.py` script, a new interactive dashboard, and standalone scripts for direct manual control.

#### Running the Bot
To start the bot, use the `trade` or `test` commands. This will run the main bot loop in the container. You should run this in one terminal window.
- **Live Trading**: `python run.py trade`
- **Paper Trading (Testnet)**: `python run.py test`

#### Monitoring with the Dashboard
To monitor a running bot, open a **second terminal window** and use the `dashboard` command.
- **To monitor the Testnet bot**: `python run.py dashboard --mode test`
- **To monitor the Live bot**: `python run.py dashboard --mode trade`

#### Direct Script-Based Control
For automation or direct manual intervention, you can use the scripts in the `scripts/` folder from your host machine's terminal.

| Command | Description |
|---|---|
| `python scripts/get_bot_data.py <mode>` | Dumps a full JSON report of the bot's status. `<mode>` can be `trade` or `test`. |
| `python scripts/force_buy.py <amount>` | Commands the bot to buy a specific USD amount of crypto. |
| `python scripts/force_sell.py <id> <pct>`| Commands the bot to sell a percentage of an open trade. Example: `... force_sell.py <trade_id> 90`. |

#### Summary of `run.py` Application Commands

| Command | Description |
|---|---|
| `trade` | Starts the bot in **live trading mode**. |
| `test` | Starts the bot in **paper trading mode**. |
| `dashboard` | Starts the new interactive TUI for monitoring and control. Use `--mode` to specify `trade` or `test`. |
| `backtest` | Prepares historical data and runs a full backtest. |
| `clear-backtest-trades` | Deletes all `backtest` trades from the database. |
| `clear-testnet-trades` | Deletes all `test` trades from the database. |


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

The bot includes a new, high-performance Terminal User Interface (TUI) for monitoring and manual control, launched with the `run.py dashboard` command. This TUI is built on the new script-based architecture, ensuring it is fast and reliable.

### TUI Preview
A preview of the new dashboard layout:
```
 +---------------------------------------------------------------------------------------------+
 | Jules Bot                                                                     मोड: TEST      |
 +---------------------------------------------------------------------------------------------+
 | Bot Control                        | Bot Status                                             |
 | Manual Buy (USD): [ 50.00 ]        | Symbol: BTC/USDT   Price: $34,567.89                     |
 | [ FORCE BUY ]                      |                                                        |
 |                                    | Open Positions                                         |
 | Selected Trade Actions (ID: ab12)  | ID   | Entry   | Value   | PnL     | Sell Target | Pr.. |
 | [ Sell 100% ] [ Sell 90% ]         |------|---------|---------|---------|-------------|------|
 |                                    | ab12 | 34000.0 | $345.67 | +$5.67  | $35000.0    | 56.7%|
 | Live Log                           | cd34 | 33950.0 | $691.35 | +$11.35 | $34800.0    | 70.1%|
 | [INFO] Bot cycle complete.         |                                                        |
 | [ERROR] Failed to fetch...         | Wallet Balances                                        |
 |                                    | Asset | Free      | Locked    | USD Value              |
 |                                    |-------|-----------|-----------|------------------------|
 |                                    | BTC   | 0.01234567| 0.00000000| $427.81                  |
 |                                    | USDT  | 1000.00   | 0.00      | $1000.00               |
 +---------------------------------------------------------------------------------------------+
```

### Key UI Features

- **Live Status**: Real-time updates on the bot's mode and the current asset price.
- **Bot Control**: A panel to manually trigger a buy order for a specific USD amount.
- **Live Log Panel**: A dedicated panel that streams the bot's most important messages directly from its structured log file, with color-coding for different log levels.
- **Open Positions Table**: A detailed list of all open trades, including unrealized PnL and a progress bar showing how close each position is to its sell target.
- **Manual Intervention**: Select a trade in the table to bring up options to **Force Sell** either 100% or 90% of the position.
