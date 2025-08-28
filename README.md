# GCS Trading Bot: Comprehensive Documentation

This document provides a complete guide to the GCS Trading Bot, a sophisticated, data-driven automated trading system for the BTC/USDT market.

## Table of Contents

1.  [**Overview**](#1-overview)
    - What is the GCS Trading Bot?
    - Key Principles
2.  [**Core Features**](#2-core-features)
3.  [**System Architecture**](#3-system-architecture)
    - Architectural Diagram
    - Component Breakdown
    - The Docker-Centric Workflow
4.  [**Setup and Installation**](#4-setup-and-installation)
    - Prerequisites
    - Step 1: Clone and Configure
    - Step 2: Start the Environment
5.  [**User Guide: A Typical Workflow**](#5-user-guide-a-typical-workflow)
    - Step 1: Start the Services
    - Step 2: Run the Bot
    - Step 3: Monitor with the Dashboard
    - Step 4: Stop Everything
6.  [**Complete Command Reference**](#6-complete-command-reference)
    - `run.py`: The Main Control Script
    - `scripts/`: Directory for Direct Interaction
7.  [**Execution Environment Clarification**](#7-execution-environment-clarification)
    - Why Docker?
    - Can I Run it Without Docker?
8.  [**Data and Database**](#8-data-and-database)
    - Database Schema
    - Log File Management
9.  [**Troubleshooting**](#9-troubleshooting)

---

## 1. Overview

### What is the GCS Trading Bot?

The GCS Trading Bot is a powerful, fully automated trading bot designed for the BTC/USDT spot market on the Binance exchange. It is not a simple, rule-based bot; instead, it leverages a robust data pipeline, machine learning for market regime detection, and a flexible, containerized architecture. This design supports live trading, paper trading (on the Binance testnet), and comprehensive backtesting capabilities.

### Key Principles

- **Data-Driven:** Decisions are based on a rich dataset, including price action, technical indicators, order flow, market sentiment, and macroeconomic data.
- **Reproducibility:** The entire application stack is containerized using Docker. This guarantees that the environment is consistent and eliminates "it works on my machine" problems.
- **Script-Based Control:** All interactions are handled through a command-line interface (`run.py`) and a collection of powerful scripts. This is a deliberate design choice for reliability, speed, and ease of automation.
- **Modularity:** The codebase is organized into decoupled components, making it easier to maintain, test, and extend.

## 2. Core Features

- **Multiple Execution Modes**:
  - **Live Trading**: Execute trades with real capital.
  - **Paper Trading**: Trade on the Binance testnet without risking real funds.
  - **Backtesting**: Simulate strategies on historical data to evaluate performance.
- **Situational Awareness Model**: Utilizes a K-Means clustering model to classify the market into "regimes" (e.g., _Bull Volatile_, _Bear Quiet_), allowing the strategy to adapt to changing conditions.
- **Interactive Terminal UI (TUI)**: A high-performance dashboard (`run.py display`) provides a real-time view of the bot's status, open positions, wallet balances, and live logs.
- **Automated Data Pipeline**: A built-in collector (`collectors/core_price_collector.py`) automatically ingests and stores all required price data in a PostgreSQL time-series database.

## 3. Trading Strategy and Configuration

The bot's decision-making is governed by a sophisticated, configurable strategy that adapts to market conditions.

### Buy Strategies Explained

The bot doesn't use a single, simple rule to buy. Instead, its behavior changes based on the market trend and its current state. The core logic is found in `jules_bot/core_logic/strategy_rules.py`.

The main buy scenarios are:

1.  **In an Uptrend (Price > 100-period EMA):**
    *   **Aggressive First Entry**: If the bot has no open positions and detects a strong uptrend (Price > 20-period EMA), it makes an initial purchase to establish a position early.
    *   **Dip Buying / Pullbacks**: If the bot already has positions, it waits for the price to temporarily dip below a shorter-term average (like the 20-period EMA) or hit a calculated dip target (a percentage drop from the recent high). This allows the bot to add to its position at a better price during an overall uptrend.

2.  **In a Downtrend (Price < 100-period EMA):**
    *   **Volatility Breakout (Bottom Fishing)**: The bot becomes much more conservative. It will only buy if the price drops below a dynamically calculated target based on the lower Bollinger Band. This is a "bottom-fishing" strategy that aims to buy when the price is significantly oversold and likely to revert.
    *   **Dynamic Difficulty**: This is a key risk management feature. The buy target in a downtrend becomes progressively harder to hit based on certain conditions, preventing the bot from over-investing in a falling market.

### Strategy Configuration Variables

You can fine-tune almost every aspect of the trading strategy by editing the variables in your `.env` file (e.g., `.env.mybot`).

#### Main Strategy Switches

| Variable | Default | Description |
| --- | --- | --- |
| `STRATEGY_RULES_USE_DYNAMIC_CAPITAL` | `True` | **Master switch for the dynamic difficulty logic.** If `False`, the bot will not use the consecutive buy logic to adjust its buy target. |
| `STRATEGY_RULES_USE_REVERSAL_BUY_STRATEGY` | `True` | If `True`, the bot will enter a "monitoring mode" on a dip instead of buying instantly. It then waits for the price to rise by a certain percentage before buying, confirming a reversal. |

#### Dynamic Difficulty Parameters

These variables control the new consecutive buy logic. They are only active if `USE_DYNAMIC_CAPITAL` is `True`.

| Variable | Default | Description |
| --- | --- | --- |
| `STRATEGY_RULES_CONSECUTIVE_BUYS_THRESHOLD` | `5` | The number of consecutive buys (without a sell) required to trigger the difficulty adjustment. |
| `STRATEGY_RULES_DIFFICULTY_RESET_TIMEOUT_HOURS` | `2` | If the bot doesn't make a new purchase for this many hours, the consecutive buy count resets to zero. |
| `STRATEGY_RULES_DIFFICULTY_ADJUSTMENT_FACTOR`| `0.005` | The factor used to lower the buy target when difficulty is active. `0.005` corresponds to a `0.5%` adjustment. |

#### Order Sizing

| Variable | Default | Description |
| --- | --- | --- |
| `STRATEGY_RULES_USE_FORMULA_SIZING` | `True` | If `True`, order size is calculated with a logarithmic formula based on total portfolio value. |
| `STRATEGY_RULES_USE_PERCENTAGE_BASED_SIZING` | `True` | If `USE_FORMULA_SIZING` is `False`, this uses a fixed percentage of your free cash for each order. |
| `REGIME_X_ORDER_SIZE_USD` | `10` | If both of the above are `False`, the bot uses a fixed USD amount for each buy, defined per market regime. |

## 4. Bot Management Workflow

Managing multiple bots is handled through a simple, interactive command-line workflow.

| Command                   | Description                                                                 |
| ------------------------- | --------------------------------------------------------------------------- |
| `python run.py new-bot`   | Creates a new bot by asking for a name and copying the template `.env` file.  |
| `python run.py test`      | Runs a bot in test mode. A menu will appear to select which bot to run.       |
| `python run.py trade`     | Runs a bot in live mode. A menu will appear to select which bot to run.       |
| `python run.py display`   | Displays the TUI for a running bot. A menu will appear for selection.         |
| `python run.py delete-bot`| Deletes a bot after interactive selection and confirmation.                   |

## 5. System Architecture

### Architectural Diagram

The system is centered around a main bot process running inside a Docker container. It is controlled and monitored via local scripts that interact with the container.

```
   HOST MACHINE                                  DOCKER CONTAINER
+-------------------+      +------------------+      +---------------------+
|      run.py       |----->| docker-compose   |----->|  jules_bot/main.py  |
| (Control Script)  |      | (Service Mgmt)   |      |  (Bot Entry Point)  |
+-------------------+      +------------------+      +---------------------+
        ^                                                    |
        |                                                    V
+-------------------+      +----------------+      +-----------------------+
|  scripts/*.py     |<---->|   commands/    |<---->|  TradingBot           |
| (Manual Commands) |      | (File-based    |      |  (Orchestrator)       |
+-------------------+      |    Queue)      |      +-----------------------+
        ^                  +----------------+
        |
+-------------------+
|  tui/app.py       |
| (Dashboard)       |
+-------------------+
```

### Component Breakdown

- **`run.py` (CLI)**: The main entry point for managing the bot's lifecycle (starting, stopping, running commands). This script runs on your **host machine**.
- **`docker-compose.yml`**: Defines the services that make up the application stack: the Python application (`app`), the PostgreSQL database (`postgres`), and a database admin tool (`pgadmin`).
- **`jules_bot/main.py`**: The entry point for the application _inside_ the Docker container. It instantiates and starts the main `TradingBot` orchestrator.
- **`TradingBot`**: The central orchestrator. It runs the main trading loop and continuously checks the `commands/` directory for manual instructions (e.g., a `force_buy.json` file).
- **`scripts/`**: A folder of standalone Python scripts that run on your **host machine**. They provide direct control by creating command files or fetching data from the bot.
- **`tui/app.py`**: The Textual-based dashboard. It runs on your **host machine** and uses the `scripts/` to get data and issue commands.

### The Docker-Centric Workflow

The bot application itself **always runs inside the `app` Docker container**. The `run.py` script on your host machine is a convenience wrapper that executes commands _inside_ that container using `docker-compose exec`. This is a crucial concept to understand.

## 6. Setup and Installation

### Prerequisites

- **Docker and Docker Compose**: Ensure Docker is installed and running. This is non-negotiable.
- **Python 3.10+**: Required for running the `run.py` control script on your host machine.
- **Git**: For cloning the repository.
- **(Windows Users)**: It is highly recommended to use **Windows Terminal** for the best experience, especially for the TUI dashboard. The legacy `cmd.exe` may have rendering issues.

### Step 1: Clone and Configure

1.  Clone the repository and navigate into the directory.
    ```bash
    git clone <YOUR_REPOSITORY_URL>
    cd gcsbot-btc
    ```
2.  Create your environment configuration file from the example.
    ```bash
    cp .env.example .env
    ```
3.  Edit the `.env` file with your Binance API keys (and any other custom settings).

> **Important**: If you change the `.env` file after starting the services, you must restart them for the changes to take effect: `python run.py stop` followed by `python run.py start`.

### Step 2: Start the Environment

The `start` command will build the Docker images (if they don't exist) and launch the `app`, `postgres`, and `pgadmin` services in the background.

```bash
python run.py start
```

The `app` container will start and remain in an idle state, waiting for you to issue a command.

## 7. User Guide: A Simplified Workflow

With the new interactive capabilities, managing and running your bots is easier than ever.

### Step 1: Create Your First Bot

If you haven't configured a bot yet, you can create one easily. This will create a `.env.mybot` file for you to edit.
```bash
python run.py new-bot
# Follow the prompt and enter a name, e.g., "mybot"
```
Now, open `.env.mybot` and add your API keys.

### Step 2: Start the Services

In your terminal, start all Docker services. This only needs to be done once.
```bash
python run.py start
```

### Step 3: Run the Bot

Open a **new terminal window**. To run your bot in paper trading (testnet) mode, just use the `test` command.
```bash
python run.py test
```
Since you now have more than one bot, an interactive menu will appear. Select `mybot` from the list and press Enter. The bot will start running and display its live logs in this terminal.

### Step 4: Monitor with the Display

Open a **third terminal window**. Launch the TUI (Text-based User Interface).
```bash
python run.py display
```
Again, the interactive menu will appear. Select the running bot (`mybot`) to start the dashboard.

### Step 5: Stop Everything

When you are finished, you can stop all services with a single command:
```bash
python run.py stop
```

## 8. Complete Command Reference

### `run.py`: The Main Control Script

These commands are your primary way of managing the bot's environment and application.

| Command                 | Description                                                                                       |
| ----------------------- | ------------------------------------------------------------------------------------------------- |
| `start`                 | Builds and starts all services (`app`, `postgres`, `pgadmin`) in detached mode.                   |
| `stop`                  | Stops and removes all running services and associated volumes.                                    |
| `status`                | Shows the current status of all running Docker services.                                          |
| `build`                 | Forces a rebuild of the Docker images without starting them. Use after changing the `Dockerfile`. |
| `logs [service]`        | Tails the logs of a specific service (e.g., `app`, `db`) or all services if none is specified.    |
| `new-bot`               | Starts an interactive prompt to create a new bot configuration file.                              |
| `delete-bot`            | Starts an interactive prompt to delete an existing bot's configuration file.                      |
| `trade`                 | Starts the bot in **live trading mode**. Shows a selection menu if `--bot-name` is not used.      |
| `test`                  | Starts the bot in **paper trading (testnet) mode**. Shows a selection menu if `--bot-name` is not used. |
| `display --mode <m>`    | Starts the interactive TUI. Shows a selection menu if `--bot-name` is not used.                   |
| `backtest --days <d>`   | Prepares historical data and runs a full backtest for the specified number of days.               |
| `clear-testnet-trades`  | **DESTRUCTIVE:** Deletes all `test` environment trades from the PostgreSQL database.              |
| `clear-backtest-trades` | **DESTRUCTIVE:** Deletes all `backtest` environment trades from the PostgreSQL database.          |
| `wipe-db`               | **EXTREMELY DESTRUCTIVE:** Wipes all data from the primary tables after a confirmation prompt.    |

### `scripts/`: Directory for Direct Interaction

These scripts can be run from your host machine's terminal for automation or direct manual intervention. They work by executing code inside the running `app` container.

| Script                        | Description                                                                                    | Arguments                                |
| ----------------------------- | ---------------------------------------------------------------------------------------------- | ---------------------------------------- |
| `analyze_results.py`          | Analyzes trade performance against model confidence.                                           | `--env <name>` (Default: `trade`)        |
| `get_bot_data.py`             | Dumps a JSON report of the bot's current status (used by the TUI).                             | `mode` (Default: `test`)                 |
| `force_buy.py`                | Issues a manual buy command to a running bot.                                                  | `amount_usd` (Required)                  |
| `force_sell.py`               | Issues a manual sell command to a running bot.                                                 | `trade_id`, `percentage` (Required)      |
| `prepare_backtest_data.py`    | Fetches and prepares historical data for backtesting.                                          | `days` (Required)                        |
| `run_backtest.py`             | Runs a backtesting simulation on already-prepared data.                                        | `days` or (`--start-date`, `--end-date`) |
| `verify_data.py`              | Checks data integrity in the database.                                                         | None                                     |
| `clear_testnet_trades.py`     | **DESTRUCTIVE:** Clears all `test` environment trades from PostgreSQL.                         | None                                     |
| `clear_trades_measurement.py` | **DESTRUCTIVE:** Clears all data from the `trades` measurement for a given environment.        | `--env <name>` (Required)                |
| `wipe_database.py`            | **EXTREMELY DESTRUCTIVE:** Wipes all tables in the PostgreSQL database. Requires confirmation. | None                                     |

## 9. Execution Environment Clarification

### Why Docker?

The bot is designed to run within a Docker container for a several critical reasons:

1.  **Consistency:** It ensures that the bot runs in the exact same environment every time, with the same dependencies and configuration, regardless of your host operating system.
2.  **Dependency Management:** All Python and system-level dependencies are managed within the `Dockerfile`, preventing conflicts with other projects on your machine.
3.  **Portability:** The entire application can be easily moved and run on any machine that has Docker installed.

### Can I Run it Without Docker?

**No.** The intended and only supported method of running the bot application is through the provided Docker setup managed by `run.py`.

While you may see a `.venv` directory if you are developing on the code, this virtual environment is for your IDE to provide features like code completion and linting. It is **not** for running the bot itself. The `run.py` script and the `scripts/` are the only components designed to be executed directly on your host machine, and their purpose is to control the bot running inside Docker.

## 10. Data and Database

### Database Schema

The application uses a PostgreSQL database with three main tables: `price_history`, `trades`, and `bot_status`. For a detailed breakdown of each table's columns, refer to the `jules_bot/database/models.py` file.

### Log File Management

The bot generates structured JSON logs in the `logs/` directory. This directory is created automatically.

- `jules_bot.jsonl`: The main application log.
- `performance.jsonl`: A log specifically for performance metrics.

To prevent excessive disk usage, the log files are automatically rotated. **Only the most recent 2 days of logs are kept.** Older log files are automatically deleted.

## 11. Troubleshooting

**"Docker Compose not found" error:**

- Ensure Docker Desktop (or Docker Engine) is installed correctly and that the Docker daemon is running.
- On Linux, you may need to install `docker-compose` separately or use `docker compose` (with a space). The `run.py` script tries to detect this automatically. You might also need to run commands with `sudo`.

**TUI Dashboard is not rendering correctly:**

- If you are on Windows, ensure you are using Windows Terminal.
- If you are on macOS or Linux, ensure your terminal supports standard color and character rendering (most modern terminals do).
- Make sure your terminal window is large enough to draw the UI components.

**Changes to `.env` file not working:**

- You must restart the Docker services for changes in the `.env` file to be loaded. Run `python run.py stop` and then `python run.py start`.

## 12. Terminal User Interface (TUI)

The bot includes a high-performance Terminal User Interface (TUI) for monitoring and manual control, launched with the `run.py display` command.

If you have multiple bots, `run.py display` will first ask you which bot you want to monitor.

### Key UI Features

- **Live Status**: Real-time updates on the bot's mode, the current asset price, wallet value, and open position count.
- **Strategy Status Panel**: Shows the current operating mode, the detected market regime, and the *actual* condition the bot is waiting for. This is no longer a simple "dip target" but a reflection of the real strategy rules (e.g., waiting for price to cross an EMA or a Bollinger Band).
- **Bot Control**: A panel to manually trigger a `FORCE BUY` order for a specific USD amount.
- **Live Log Panel**: Streams the bot's most important messages directly from its log file, with color-coding for different log levels and a filter bar.
- **Open Positions Table**: A detailed list of all open trades, including unrealized PnL and a progress bar showing how close each position is to its sell target.
- **Manual Intervention**: Select a trade in the table to enable the `FORCE SELL` buttons, allowing you to close a position manually.
- **Portfolio Evolution**: Tracks the overall performance of your portfolio over time, including total and 24-hour percentage change.
- **DCOM Status**: Displays the status of the Dynamic Capital & Operations Management system, including total equity, working capital, and the strategic reserve.

## 13. Status Data Structure

The `scripts/get_bot_data.py` script provides a comprehensive JSON snapshot of the bot's current state. This data is used to populate the TUI and can be used for any external monitoring. Below is an example of the structure with explanations for each key.

```json
{
  "mode": "test",
  "symbol": "BTC/USDT",
  "current_btc_price": 51000.5,
  "total_wallet_usd_value": 11500.25,
  "open_positions_status": [
    {
      "trade_id": "a1b2c3d4-e5f6-7890-g1h2-i3j4k5l6m7n8",
      "entry_price": 50000.0,
      "current_price": 51000.5,
      "quantity": 0.1,
      "unrealized_pnl": 100.05,
      "sell_target_price": 55000.0,
      "progress_to_sell_target_pct": 20.01,
      "price_to_target": 3999.5,
      "usd_to_target": 399.95
    }
  ],
  "buy_signal_status": {
    "should_buy": false,
    "reason": "Price $65123.45 is above adjusted BBL $65000.00",
    "market_regime": 2,
    "operating_mode": "ACCUMULATION",
    "condition_label": "Price > Adj. BBL",
    "condition_target": "$65000.00",
    "condition_progress": 50.5
  },
  "trade_history": [
    {
      "trade_id": "z9y8x7w6-v5u4-t3s2-r1q0-p9o8n7m6l5k4",
      "status": "CLOSED",
      "realized_pnl_usd": 50.75,
      "...": "other trade fields"
    }
  ],
  "wallet_balances": [
    {
      "asset": "BTC",
      "free": "0.1",
      "locked": "0.0",
      "usd_value": 5100.05
    },
    {
      "asset": "USDT",
      "free": "6400.20",
      "locked": "0.0",
      "usd_value": 6400.2
    }
  ]
}
```

### Key Descriptions

- **`mode`**: The environment the bot is running in (`trade`, `test`).
- **`symbol`**: The trading pair being monitored.
- **`current_btc_price`**: The latest price of BTC.
- **`total_wallet_usd_value`**: The total estimated value of the wallet in USD, summing the value of all assets (BTC and USDT).
- **`open_positions_status`**: A list of currently open positions.
  - `trade_id`: The unique ID for the trade.
  - `entry_price`: The price at which the asset was bought.
  - `current_price`: The current market price.
  - `quantity`: The amount of the asset held.
  - `unrealized_pnl`: The current paper profit or loss for the position.
  - `sell_target_price`: The price at which the strategy aims to sell.
  - `progress_to_sell_target_pct`: The percentage progress towards the sell target.
  - `price_to_target`: The absolute price difference to the sell target.
  - `usd_to_target`: The USD value of the `price_to_target`.
- **`buy_signal_status`**: Real-time information about the bot's readiness to make a new buy, reflecting the true strategy.
  - `should_buy`: A boolean indicating if the strategy conditions for a buy are currently met.
  - `reason`: The raw, human-readable explanation from the strategy engine.
  - `market_regime`: The market regime detected by the Situational Awareness model.
  - `operating_mode`: The bot's current capital management mode (e.g., `ACCUMULATION`).
  - `condition_label`: A short label for the condition being monitored (e.g., `Price > Adj. BBL`).
  - `condition_target`: The actual value of the target the bot is waiting for.
  - `condition_progress`: The percentage progress towards meeting the `condition_target`.
- **`trade_history`**: A list of all trades (open and closed) for the environment.
- **`wallet_balances`**: A list of balances for relevant assets from the exchange.
  - `asset`: The ticker for the asset (e.g., `BTC`).
  - `free`: The amount of the asset that is available to trade.
  - `locked`: The amount of the asset that is currently in open orders.
  - `usd_value`: The estimated value of the asset balance in USD.
