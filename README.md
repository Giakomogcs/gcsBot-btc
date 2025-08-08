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
- **Automated Data Pipeline**: A powerful ETL script (`scripts/data_pipeline.py`) automatically ingests, processes, and stores all required data in an InfluxDB time-series database.
- **Situational Awareness Model**: Utilizes a K-Means clustering model to classify the market into one of several "regimes" (e.g., Bull Volatile, Bear Quiet), allowing the strategy to adapt to changing conditions.
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
+---------------+ +---------------------+ +--------------------------+
| PositionManager |   AccountManager    |      DatabaseManager     |
| (Strategy)    |   (Execution)       |      (Persistence)       |
+---------------+ +---------------------+ +--------------------------+
      |                 |                  |
      |                 V                  |
      |       +-------------------+        |
      +------>| ExchangeManager   |<-------+
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
├── config/              # Configuration files for services (e.g., influxdb.conf)
├── data/                # Local data storage (e.g., historical CSVs, models)
├── jules_bot/           # Main Python source code for the bot application
│   ├── bot/             # Core trading logic, position management, and feature engineering
│   ├── core/            # Core components like the exchange connector
│   ├── database/        # Database interaction and data management
│   └── utils/           # Utility modules like logging and configuration management
├── logs/                # Log files and trading status JSONs
├── scripts/             # Standalone Python scripts for automation and analysis
├── tests/               # Automated tests for the application
├── .env.example         # Example environment variables file
├── config.yml           # Main application configuration file
├── docker-compose.yml   # Docker service definitions
├── Dockerfile           # Docker image definition for the application
└── run.py               # Main command-line interface for controlling the bot
```

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
- **Automated Data Pipeline**: A powerful ETL script (`scripts/data_pipeline.py`) automatically ingests, processes, and stores all required data in an InfluxDB time-series database.
- **Situational Awareness Model**: Utilizes a K-Means clustering model to classify the market into one of several "regimes" (e.g., Bull Volatile, Bear Quiet), allowing the strategy to adapt to changing conditions.
- **Dockerized Environment**: The entire application stack, including the Python application and the InfluxDB database, is managed by Docker and Docker Compose for easy setup and deployment.
- **Command-Line Interface**: A central script `run.py` provides a simple interface for managing the entire lifecycle of the bot and its environment.
- **Resilient and Modular Architecture**: The code is organized into decoupled components (bot logic, database management, exchange connection), making it easier to maintain and extend.

## 3. Architecture

The bot is designed with a modular architecture, separating concerns to improve maintainability and testability.

```
+-------------------+      +----------------------+      +---------------------+
|     run.py        |----->| docker-compose.yml   |----->|   jules_bot/main.py |
| (User Interface)  |      | (Service Definition) |      | (App Entry Point)   |
+-------------------+      +----------------------+      +---------------------+
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
├── config/              # Configuration files for services (e.g., influxdb.conf)
├── data/                # Local data storage (e.g., historical CSVs, models)
├── jules_bot/           # Main Python source code for the bot application
│   ├── bot/             # Core trading logic, position management, and feature engineering
│   ├── core/            # Core components like the exchange connector
│   ├── database/        # Database interaction and data management
│   └── utils/           # Utility modules like logging and configuration management
├── logs/                # Log files and trading status JSONs
├── scripts/             # Standalone Python scripts for automation and analysis
├── tests/               # Automated tests for the application
├── .env.example         # Example environment variables file
├── config.yml           # Main application configuration file
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

Run the data pipeline to download historical data, compute features, and populate the database. This will take a significant amount of time on the first run.

```bash
python run.py update-db
```

The bot is now ready to be used.

## 6. Usage

All interaction with the bot and its environment is handled by `run.py`.

**Common Commands:**

- **Start Services**: `python run.py start`

  - Starts the InfluxDB container.

- **Update Database**: `python run.py update-db`

  - Runs the full data pipeline. Should be run periodically to keep data fresh.

- **Run the Bot (Live Trading)**: `python run.py trade`

  - Starts the bot in the background, trading with real money.

- **Run the Bot (Paper Trading)**: `python run.py test`

  - Starts the bot in the background, trading on the Binance testnet.

- **Run a Backtest**: `python run.py backtest`

  - Starts a backtest run using historical data.

- **View Logs**: `python run.py logs`

  - Tails the logs of the running bot application.

- **Stop the Bot and Services**: `python run.py stop`

  - Stops and removes all running containers.

- **Reset the Database**: `python run.py reset-db`
  - **WARNING:** This is a destructive operation. It stops all services and permanently deletes all data stored in the InfluxDB volume.

For a full list of commands, run `python run.py help`.

## 7. Configuration (`config.yml`)

The `config.yml` file allows you to tune the bot's behavior without changing the code.

- **`database`**: Configures the connection details for InfluxDB. These should generally match the `docker-compose.yml` setup.
- **`app`**: Main application settings.
  - `use_testnet`: If `true`, the `test` command will use the testnet.
  - `symbol`: The trading pair to use (e.g., `BTCUSDT`).
- **`backtest`**: Parameters for backtesting simulations, including `start_date` and `initial_capital`.
- **`data_paths`**: Defines the local paths for storing data files and trained models.
- **`data_pipeline`**: Contains settings for the data pipeline, such as the features to use for regime detection (`regime_features`) and the parameters for the target calculation (`target`).
- **`trading_strategy`**: Defines the core parameters for the trading logic, such as `take_profit_percentage` and `buy_on_dip_percentage`.
- **`position_management`**: Governs how capital is allocated, including the maximum number of concurrent trades and the percentage of capital per trade.

## 8. Data Pipeline In-Depth

The data pipeline is orchestrated by `scripts/data_pipeline.py` and is the foundation of the bot's trading strategy.

1.  **Ingestion**: It fetches raw data from multiple sources:
    - **Binance API**: OHLCV candles, order flow data, funding rates, open interest.
    - **Alternative.me**: Fear & Greed Index for market sentiment.
    - **Yahoo Finance**: Macroeconomic data (DXY, VIX, Gold, SPX, etc.).
2.  **Feature Engineering**: The raw data is enriched with a wide array of calculated features using `jules_bot/bot/feature_engineering.py`. This includes technical indicators, volume analysis, and intermarket correlations.
3.  **Regime Detection**: A K-Means clustering model (`jules_bot/bot/situational_awareness.py`) is used to classify the market state into different "regimes" based on volatility, momentum, and other factors. This allows the trading logic to be context-aware.
4.  **Storage**: The final, feature-rich DataFrame is stored in the `features_master_table` measurement in InfluxDB, ready to be queried by the trading bot.

This entire process is run by executing `python run.py update-db`.

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

Run the data pipeline to download historical data, compute features, and populate the database. This will take a significant amount of time on the first run.

```bash
python run.py update-db
```

The bot is now ready to be used.

## 6. Usage

All interaction with the bot and its environment is handled by `run.py`.

**Common Commands:**

- **Start Services**: `python run.py start`

  - Starts the InfluxDB container.

- **Update Database**: `python run.py update-db`

  - Runs the full data pipeline. Should be run periodically to keep data fresh.

- **Run the Bot (Live Trading)**: `python run.py trade`

  - Starts the bot in the background, trading with real money.

- **Run the Bot (Paper Trading)**: `python run.py test`

  - Starts the bot in the background, trading on the Binance testnet.

- **Run a Backtest**: `python run.py backtest`

  - Starts a backtest run using historical data.

- **View Logs**: `python run.py logs`

  - Tails the logs of the running bot application.

- **Stop the Bot and Services**: `python run.py stop`

  - Stops and removes all running containers.

- **Reset the Database**: `python run.py reset-db`
  - **WARNING:** This is a destructive operation. It stops all services and permanently deletes all data stored in the InfluxDB volume.

For a full list of commands, run `python run.py help`.

## 7. Configuration (`config.yml`)

The `config.yml` file allows you to tune the bot's behavior without changing the code.

- **`database`**: Configures the connection details for InfluxDB. These should generally match the `docker-compose.yml` setup.
- **`app`**: Main application settings.
  - `use_testnet`: If `true`, the `test` command will use the testnet.
  - `symbol`: The trading pair to use (e.g., `BTCUSDT`).
- **`backtest`**: Parameters for backtesting simulations, including `start_date` and `initial_capital`.
- **`data_paths`**: Defines the local paths for storing data files and trained models.
- **`data_pipeline`**: Contains settings for the data pipeline, such as the features to use for regime detection (`regime_features`) and the parameters for the target calculation (`target`).
- **`trading_strategy`**: Defines the core parameters for the trading logic, such as `take_profit_percentage` and `buy_on_dip_percentage`.
- **`position_management`**: Governs how capital is allocated, including the maximum number of concurrent trades and the percentage of capital per trade.

## 8. Data Pipeline In-Depth

The data pipeline is orchestrated by `scripts/data_pipeline.py` and is the foundation of the bot's trading strategy.

1.  **Ingestion**: It fetches raw data from multiple sources:
    - **Binance API**: OHLCV candles, order flow data, funding rates, open interest.
    - **Alternative.me**: Fear & Greed Index for market sentiment.
    - **Yahoo Finance**: Macroeconomic data (DXY, VIX, Gold, SPX, etc.).
2.  **Feature Engineering**: The raw data is enriched with a wide array of calculated features using `jules_bot/bot/feature_engineering.py`. This includes technical indicators, volume analysis, and intermarket correlations.
3.  **Regime Detection**: A K-Means clustering model (`jules_bot/bot/situational_awareness.py`) is used to classify the market state into different "regimes" based on volatility, momentum, and other factors. This allows the trading logic to be context-aware.
4.  **Storage**: The final, feature-rich DataFrame is stored in the `features_master_table` measurement in InfluxDB, ready to be queried by the trading bot.

This entire process is run by executing `python run.py update-db`.
