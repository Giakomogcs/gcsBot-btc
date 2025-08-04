# GCS-Bot: The GCS-Bot Manifesto

## Core Philosophy
A synthesis of four non-negotiable pillars that will guide every line of code and strategic decision.

*   **Discipline:** The system must execute its rules without emotion or deviation. All logic for entry, management, and exit must be absolute and auditable. Each trade is a sovereign entity, managed from inception to conclusion based on mathematical criteria.
*   **Adaptation:** The market is a living organism. Our bot will not be a rigid statue. It will adapt its risk, confidence, and strategy based on market regimes (e.g., high/low volatility, trending/ranging).
*   **Robustness:** The system is a battle tank. Built on the principles of Defensive Software Engineering, it anticipates and handles real-world imperfections—missing data, API errors, network latency—without ever failing its core mission.
*   **Transparency:** The bot cannot be a "black box." Using Explainable AI (XAI) techniques, we will have a window into our AI's mind, allowing us to understand the "why" behind each decision, build trust, and iterate with intelligence.

## Architecture

The project is organized into a clean, professional, and scalable structure adhering to Python packaging standards.

### Folder Structure Diagram

```
gcs-bot/
├── gcs_bot/
│   ├── core/
│   │   ├── backtester.py
│   │   ├── ensemble_manager.py
│   │   ├── position_manager.py
│   │   └── ... (The bot's brain: other core logic)
│   ├── data/
│   │   ├── data_manager.py
│   │   ├── feature_engineering.py
│   │   └── feature_selector.py
│   ├── database/
│   │   └── database_manager.py
│   └── utils/
│       ├── config_manager.py
│       └── logger.py
├── scripts/
│   ├── run_backtest.py
│   ├── run_optimizer.py
│   ├── data_pipeline.py
│   └── analyze_results.py
├── tests/
├── config.yml
├── manage.ps1
└── README.md
```

### Module Interaction

*   **`manage.ps1`**: The main entry point for all operations. This PowerShell script orchestrates Docker commands to run the various components of the bot.
*   **`scripts/`**: Contains high-level executable scripts that perform specific tasks like running a backtest (`run_backtest.py`), training models (`run_optimizer.py`), or populating the database (`data_pipeline.py`).
*   **`gcs_bot/`**: The main Python package containing all the application source code.
    *   **`core/`**: The bot's brain. It houses the central logic for backtesting, position management, and AI model ensembles.
    *   **`data/`**: Modules responsible for fetching, cleaning, processing, and engineering features from raw market data.
    *   **`database/`**: A dedicated module to handle all interactions with the time-series database (InfluxDB).
    *   **`utils/`**: Shared utilities for tasks like managing configuration (`config.yml`) and logging.

## Control Panel (`manage.ps1`)

Use this PowerShell script to manage the entire bot lifecycle.

### Environment Management
*   `.\manage.ps1 setup`: Configures the Docker environment completely for the first time.
*   `.\manage.ps1 start-services`: Starts the required Docker containers (app, db).
*   `.\manage.ps1 stop-services`: Stops the running Docker containers.
*   `.\manage.ps1 reset-db`: **DANGER!** Stops and completely erases the database volume.
*   `.\manage.ps1 clean-master`: Deletes only the `features_master_table` to be rebuilt.
*   `.\manage.ps1 reset-trades`: Deletes only the trade history from the database.
*   `.\manage.ps1 reset-sentiment`: Deletes only the sentiment data history.

### Bot Operations
*   `.\manage.ps1 update-db`: Runs the complete ETL pipeline to populate and update the database with the latest market data.
*   `.\manage.ps1 optimize`: Starts the AI model training and optimization process.
*   `.\manage.ps1 backtest`: Runs a backtest using the currently trained models.
*   `.\manage.ps1 run-live`: **DANGER!** Starts the bot in live trading mode.
*   `.\manage.ps1 analyze`: Analyzes the results of the last backtest run.
*   `.\manage.ps1 analyze-decision <model_name> "<timestamp>"`: Provides an XAI analysis for a specific model's decision at a given time.

## Quick Start Guide

1.  **Prerequisites**:
    *   Docker Desktop (must be running)
    *   PowerShell

2.  **Setup the Environment**:
    Open a PowerShell terminal and run the setup command. This will build the Docker images and start the necessary services.
    ```powershell
    .\manage.ps1 setup
    ```

3.  **Populate the Database**:
    Run the data pipeline to download, process, and store all the necessary market data in the database.
    ```powershell
    .\manage.ps1 update-db
    ```

4.  **Train the AI Models**:
    Run the optimizer to train the machine learning models on the historical data. This can be a long process.
    ```powershell
    .\manage.ps1 optimize
    ```

5.  **Run a Backtest**:
    Once the models are trained, run a backtest to simulate the strategy and evaluate its performance.
    ```powershell
    .\manage.ps1 backtest
    ```

6.  **Analyze the Results**:
    After the backtest is complete, generate a performance report.
    ```powershell
    .\manage.ps1 analyze
    ```
