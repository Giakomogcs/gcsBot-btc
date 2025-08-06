# GCS-Bot: The GCS-Bot Manifesto

## Core Philosophy
A synthesis of four non-negotiable pillars that will guide every line of code and strategic decision.

*   **Discipline:** The system must execute its rules without emotion or deviation. All logic for entry, management, and exit must be absolute and auditable. Each trade is a sovereign entity, managed from inception to conclusion based on mathematical criteria.
*   **Adaptation:** The market is a living organism. Our bot will not be a rigid statue. It will adapt its risk, confidence, and strategy based on market regimes (e.g., high/low volatility, trending/ranging).
*   **Robustness:** The system is a battle tank. Built on the principles of Defensive Software Engineering, it anticipates and handles real-world imperfections—missing data, API errors, network latency—without ever failing its core mission.
*   **Transparency:** The bot cannot be a "black box." Using the new dashboard, we have a clear window into the bot's real-time operations, account status, and performance.

## Architecture

The project is organized into a clean, professional, and scalable structure adhering to Python packaging standards.

### Module Interaction

*   **`run.py`**: The main command-line interface (CLI) for all operations. This Python script orchestrates Docker commands to run the various components of the bot.
*   **`gcs_bot/`**: The main Python package containing all the application source code.
    *   **`core/`**: The bot's brain. It houses the central logic for trading, position management, and account interaction.
    *   **`database/`**: A dedicated module to handle all interactions with the InfluxDB time-series database.
    *   **`utils/`**: Shared utilities for configuration management and logging.

## Control Panel (`run.py`)

Use this Python script to manage the entire bot lifecycle. All commands are executed via `python3 run.py [command]`.

### Environment Management
*   `setup`: Builds and starts the Docker environment for the first time.
*   `start-services`: Starts the Docker containers (app, db).
*   `stop-services`: Stops the Docker containers.
*   `reset-db`: **DANGER!** Stops and erases the database.

### Bot Operations & Modes
*   `trade`: Starts the bot in **live trading mode** (real money) in a background container.
*   `test`: Starts the bot in **test mode** (live data on Binance Testnet) in a background container.
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

## Trading Dashboard

The trading dashboard provides a real-time overview of the bot's performance and status. To view it, run `python3 run.py show_trading` while the bot is running in `trade` or `test` mode.

The dashboard includes:
*   **Portfolio:** Your current BTC and USDT balances, and the total value of your portfolio.
*   **Session Stats:** Total realized Profit & Loss, and counts of open and closed trades.
*   **Bot's Internal Trades:** A summary of the last few trades as recorded by the bot.
*   **Binance Open Orders:** A list of open orders for the trading symbol, fetched directly from Binance.
*   **Binance Trade History:** Your recent trade history for the symbol, fetched directly from Binance for verification.

## Quick Start Guide

1.  **Prerequisites**:
    *   Docker Desktop (must be running).
    *   Python 3.10+.

2.  **Setup the Environment**:
    Open a terminal and run the setup command. This will build the Docker images and start the necessary services.
    ```bash
    python3 run.py setup
    ```
    You will also need to create a `.env` file from the `.env.example` template and fill in your Binance API keys (both mainnet and testnet) and desired InfluxDB credentials.

3.  **Run in Test Mode**:
    Before running with real money, it's highly recommended to run the bot in test mode on the Binance Testnet.
    ```bash
    python3 run.py test
    ```

4.  **Monitor the Bot**:
    To see the live trading dashboard, open a new terminal and run:
    ```bash
    python3 run.py show_trading
    ```
    To view the raw logs from the bot, run:
    ```bash
    python3 run.py logs
    ```

5.  **Run in Live Mode**:
    Once you are confident that the bot is working as expected, you can run it in live mode with real funds.
    ```bash
    python3 run.py trade
    ```

6.  **Stopping the Bot**:
    To stop the bot and its associated services, run:
    ```bash
    python3 run.py stop-services
    ```
