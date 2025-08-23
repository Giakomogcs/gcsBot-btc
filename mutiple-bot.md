# Jules Bot - A Crypto Trading Bot

Jules Bot is a flexible and powerful cryptocurrency trading bot that can be configured to run in live or testnet mode. It supports running multiple bot instances in isolation, with separate logs and database schemas for each instance.

## Prerequisites

Before you begin, ensure you have the following installed:
- [Docker](https://docs.docker.com/get-docker/)
- [Docker Compose](https://docs.docker.com/compose/install/) (v2)

## Setup

1.  **Clone the repository:**
    ```bash
    git clone <repository-url>
    cd gcsBot-btc
    ```

2.  **Create your environment file:**
    You can copy the example environment file and customize it with your API keys and other settings.
    ```bash
    cp .env.example .env
    ```
    You can create multiple `.env` files for different configurations (e.g., `.env.bot-1`, `.env.bot-2`).

3.  **Start the services:**
    This will build the Docker images and start the services in the background.
    ```bash
    python run.py start
    ```

## Running the Bot

You can run the bot in `trade` (live) or `test` (testnet) mode. You can also specify a name for your bot instance and the environment file to use.

### Options

-   `--bot-name` or `-n`: Specifies a unique name for the bot instance. This name is used for log files and database schemas. Defaults to `jules_bot`.
-   `--env-file` or `-e`: Specifies the path to the environment file to use. Defaults to `.env`.

### Running in Test Mode

To run the bot in testnet mode, use the `test` command.

**Example 1: Running a test with the default configuration**
This will use the `.env` file and the bot name `jules_bot`.
```bash
python run.py test
```

**Example 2: Running a test with a specific bot name**
This will create a log file named `logs/my-test-bot.jsonl` and a database schema named `my_test_bot`.
```bash
python run.py --bot-name my-test-bot test
```

**Example 3: Running a test with a specific bot name and environment file**
This will use the configuration from `.env.test-config` and create a bot instance named `my-test-bot`.
```bash
python run.py --bot-name my-test-bot --env-file .env.test-config test
```

### Running in Trade Mode

To run the bot in live trading mode, use the `trade` command.

**⚠️ Warning:** Running in trade mode will use real funds from your exchange account. Make sure you have configured your API keys and strategy correctly.

**Example 1: Running a trade with the default configuration**
This will use the `.env` file and the bot name `jules_bot`.
```bash
python run.py trade
```

**Example 2: Running a trade with a specific bot name**
This will create a log file named `logs/my-live-bot.jsonl` and a database schema named `my_live_bot`.
```bash
python run.py --bot-name my-live-bot trade
```

**Example 3: Running a trade with a specific bot name and environment file**
This will use the configuration from `.env.live-config` and create a bot instance named `my-live-bot`.
```bash
python run.py --bot-name my-live-bot --env-file .env.live-config trade
```

## Stopping the Bot

To stop all running services, use the `stop` command:
```bash
python run.py stop
```

## Viewing Logs

The logs for each bot instance are stored in separate files in the `logs` directory. The log file name corresponds to the bot name you specified when running the bot.

For example, if you ran a bot named `my-test-bot`, you can view its logs in `logs/my-test-bot.jsonl`.

## Database Isolation

Each bot instance has its own isolated data in the PostgreSQL database. The data is stored in a separate schema named after the bot. For example, a bot named `my-test-bot` will have its tables created in the `my_test_bot` schema.

You can use a database tool like pgAdmin (available at `http://localhost:5050`) to connect to the database and inspect the data for each bot.
