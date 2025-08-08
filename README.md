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
- **Automated Data Pipeline**: A lean price collector (`collectors/core_price_collector.py`) automatically ingests and stores all required price data in an InfluxDB time-series database.
- **Situational Awareness Model**: Utilizes a K-Means clustering model to classify the market into one of several "regimes" (e.g., Bull Volatile, Bear Quiet), allowing the strategy to adapt to changing conditions. The code for this is in the `research` directory.
- **Dockerized Environment**: The entire application stack, including the Python application and the InfluxDB database, is managed by Docker and Docker Compose for easy setup and deployment.
- **Command-Line Interface**: A central script `run.py` provides a simple interface for managing the entire lifecycle of the bot and its environment.
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
├── .dvc/                # Data Version Control (for large data files)
├── collectors/          # Scripts for collecting data
├── config/              # Configuration files for services (e.g., influxdb.conf)
├── data/                # Local data storage (e.g., historical CSVs, models)
├── jules_bot/           # Main Python source code for the bot application
│   ├── bot/             # Core trading logic and position management
│   ├── core/            # Core components like the exchange connector
│   ├── database/        # Database interaction and data management
│   └── utils/           # Utility modules like logging and configuration management
├── logs/                # Log files and trading status JSONs
├── research/            # Scripts for research and feature engineering
├── scripts/             # Standalone Python scripts for automation and analysis
├── tests/               # Automated tests for the application
├── .env.example         # Example environment variables file
├── config.ini           # Main application configuration file
├── docker-compose.yml   # Docker service definitions
├── Dockerfile           # Docker image definition for the application
└── run.py               # Main command-line interface for controlling the bot
```

## 5. Setup and Installation

### Prerequisites

- Docker and Docker Compose
- Python 3.12+ (for running the `run.py` script)

### Step 1: Configure Environment

Create a `.env` file by copying the example:

```bash
cp .env.example .env
```

Edit the `.env` file with your credentials:

- `INFLUXDB_TOKEN`: Your desired password for the database.
- `BINANCE_API_KEY` / `BINANCE_API_SECRET`: Your live Binance API keys.
- `BINANCE_TESTNET_API_KEY` / `BINANCE_TESTNET_API_SECRET`: Your testnet Binance API keys.

### Step 2: Build the Docker Images

Build the `app` and `db` images defined in `docker-compose.yml`.

```bash
python run.py build
```

### Step 3: Start Services

Start the InfluxDB database container in the background.

```bash
python run.py start
```

### Step 4: Populate the Database

Run the data pipeline to download historical price data and populate the database.

```bash
python collectors/core_price_collector.py
```

The bot is now ready to be used.

## 6. Environment Management

The entire lifecycle of the application's environment (Docker containers) is managed via the `run.py` script. These commands are wrappers around `docker-compose` and provide a simple, unified interface for all environment-related tasks.

### Common Commands

-   **Start Services**: `python run.py start`
    -   Builds the Docker images if they don't exist and starts the `app` and `db` services in detached mode. This is the standard way to start the application.

-   **Stop Services**: `python run.py stop`
    -   Stops and removes all running containers, networks, and volumes associated with the project. This provides a clean shutdown of the environment.

-   **Check Status**: `python run.py status`
    -   Shows the current status of all project containers (e.g., whether they are running, stopped, and on which ports).

-   **View Logs**: `python run.py logs [service_name]`
    -   Follows the real-time logs of the services.
    -   If a `service_name` (e.g., `app` or `db`) is provided, it will only show logs for that specific service.
    -   If no service name is given, it will show logs for all services.

-   **Build Images**: `python run.py build`
    -   Forces a rebuild of the Docker images without using the cache. This is useful when you have changed the `Dockerfile` or suspect caching issues.

### Application Commands

-   **Run a Backtest**: `python run.py backtest [--days <number_of_days>]`
    -   Runs a backtest using recent market data from the database.
    -   `--days`: Optional. Specifies the number of recent days of data to fetch for the backtest.
    -   If not provided, it defaults to the `default_lookback_days` value in `config.ini`.
    -   Example: `python run.py backtest --days 30`

-   **Launch the UI**: `python run.py show <mode>`
    -   Launches the terminal user interface to display the state of the bot.
    -   `<mode>` can be `trade` or `backtest`.

## 7. Configuration (`config.ini`)

The `config.ini` file allows you to tune the bot's behavior without changing the code.

- **`[INFLUXDB]`**: Configures the connection details for InfluxDB.
- **`[BINANCE_LIVE]`**: Your live Binance API keys.
- **`[BINANCE_TESTNET]`**: Your testnet Binance API keys.
- **`[STRATEGY_RULES]`**: Configures the dynamic trading strategy.
  - `buy_trigger_few_positions`: The percentage drop required for the next buy when there are few open positions.
  - `buy_trigger_many_positions`: The percentage drop required for the next buy when there are many open positions.
  - `buy_amount_low_allocation_multiplier`: The multiplier for the base buy amount when capital allocation is low.
  - `buy_amount_high_allocation_multiplier`: The multiplier for the base buy amount when capital allocation is high.
  - `commission_rate`: The broker's commission rate (e.g., `0.001` for 0.1%). Used to calculate the break-even price.
  - `sell_factor`: The percentage of the position to be sold (e.g., `0.9` for 90%). The remaining part is held as a long-term asset.
  - `target_profit`: The desired net profit margin for each trade (e.g., `0.005` for 0.5%).

The `sell_target_price` is calculated automatically when a new position is created, using the following formula:

```
Sell Target = (Purchase Price * (1 + Commission Rate)) / (Sell Factor * (1 - Commission Rate)) * (1 + Target Profit)
```
- **`[BACKTEST]`**: Parameters for backtesting simulations.
- **`[DATA]`**: Paths for data files.
- **`[APP]`**: Main application settings.
- **`[DATA_PIPELINE]`**: Settings for the data pipeline.

## 8. Data Pipeline In-Depth

The data pipeline is orchestrated by `collectors/core_price_collector.py` and is the foundation of the bot's trading strategy. It is responsible for fetching OHLCV price data from Binance and storing it in InfluxDB.
