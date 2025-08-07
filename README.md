# GCS Trading Bot

This is a high-frequency trading bot for BTC/USDT on Binance. It is designed to run as a background service and can be monitored through a command-line user interface.

## Architecture

The bot uses a decoupled architecture consisting of:
- **A background daemon process**: The core trading logic runs as a persistent background service. It is started and stopped using the `run.py` script.
- **A Textual UI**: A separate command-line interface can be launched to monitor the bot's state in real-time.
- **State Files**: The daemon process communicates with the UI by writing its state to `/tmp/bot_state.json`. Process management is handled via PID files in `/tmp/`.
- **Dockerized Environment**: All services, including the bot application and the InfluxDB database, are designed to be run within a Dockerized environment managed by `docker-compose`.

## Setup

### Prerequisites
- Python 3.12+
- Docker and Docker Compose

### 1. Configure Environment Variables

Create a `.env` file in the root of the project by copying the example file:
```bash
cp .env.example .env
```
Now, edit the `.env` file and fill in your actual credentials for InfluxDB and Binance.

### 2. Install Dependencies

Install the required Python packages using pip:
```bash
pip install -r requirements.txt
```
*Note: This will install all the necessary libraries, including `typer` for the command-line interface.*

### 3. Build and Start Services

The application is designed to be run with Docker Compose.

**First-time setup:**
If you are running the bot for the first time, you need to build the Docker images and run the initial data pipeline. The `setup` command handles this for you:
```bash
python run.py setup
```
This command will:
1. Build the `app` and `db` Docker images.
2. Start the services in the background.
3. Run a data pipeline script to populate the database with historical data.

**Starting services normally:**
If you have already run the setup, you can start the services with:
```bash
python run.py start-services
```

## Usage

All commands are run via the `run.py` script.

### Running the Bot

The bot can be run in three modes: `trade`, `test`, and `backtest`. Each command starts the bot as a background process.

- **Live Trading:**
  ```bash
  python run.py trade
  ```
- **Paper Trading (Testnet):**
  ```bash
  python run.py test
  ```
- **Backtesting:**
  ```bash
  python run.py backtest
  ```

### Stopping the Bot

To stop all running bot processes (trade, test, or backtest), use the `stop` command:
```bash
python run.py stop
```

### Monitoring

- **Show the UI:**
  To view the real-time status of the main trading bot, use the `show` command:
  ```bash
  python run.py show
  ```
- **View Logs:**
  To see the live log output from the bot, use the `logs` command:
  ```bash
  python run.py logs
  ```

### Other Environment Commands

- **Stop Docker Services:**
  ```bash
  python run.py stop-services
  ```
- **Reset the Database:**
  **Warning:** This will permanently delete all trade and market data.
  ```bash
  python run.py reset-db
  ```
- **Run Tests:**
  To run the automated test suite, use the `run-tests` command. This will execute `pytest` inside the running `app` container.
  ```bash
  python run.py run-tests
  ```
