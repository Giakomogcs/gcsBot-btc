import typer
import subprocess
from typing import Optional
from jules_bot.config import GCSBotConfig
from jules_bot.backtesting.engine import Backtester
from jules_bot.database.database_manager import DatabaseManager
from jules_bot.ui.display_manager import JulesBotApp

app = typer.Typer()
config_manager = GCSBotConfig()

@app.command()
def trade():
    """
    [NOT IMPLEMENTED] Starts the bot in live trading mode.
    """
    print("Live trading mode is not yet implemented.")
    # Future: Initialize TradingBot with live ExchangeManager and run it.

@app.command()
def backtest(
    data_path: str = typer.Argument(..., help="Path to the historical market data CSV file.")
):
    """
    Runs a full backtest using the provided historical data.
    """
    try:
        backtester = Backtester(data_path)
        backtester.run()
    except Exception as e:
        print(f"An error occurred during backtest: {e}")

@app.command()
def show(
    mode: str = typer.Argument("trade", help="The mode to display: 'trade' or 'backtest'")
):
    """
    Launches the Terminal UI to display the state of a bot or backtest results.
    """
    print(f"Launching UI in '{mode}' mode...")
    
    db_config_name = f"influxdb_{mode}"
    db_config = config_manager.get(db_config_name)
    if not db_config:
        print(f"Error: Configuration for mode '{mode}' not found in config.yml.")
        return

    full_db_config = {
        **config_manager.get('influxdb_connection'),
        **db_config
    }
    db_manager = DatabaseManager(config=full_db_config)

    # Pass the correctly configured db_manager to the UI app
    app_ui = JulesBotApp(db_manager=db_manager, display_mode=mode)
    app_ui.run()

if __name__ == "__main__":
    app()

env_app = typer.Typer()
app.add_typer(env_app, name="env")

@env_app.command("start")
def env_start():
    """Builds and starts all services in detached mode."""
    print("🚀 Starting Docker services via docker-compose up --build -d...")
    try:
        subprocess.run(["docker-compose", "up", "--build", "-d"], check=True)
        print("✅ Services started successfully.")
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"❌ Error starting services: {e}")
        print("Is Docker and docker-compose installed and running?")

@env_app.command("stop")
def env_stop():
    """Stops and removes all services."""
    print("🔥 Stopping Docker services via docker-compose down...")
    try:
        subprocess.run(["docker-compose", "down"], check=True)
        print("✅ Services stopped successfully.")
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"❌ Error stopping services: {e}")

@env_app.command("status")
def env_status():
    """Shows the status of all services."""
    print("📊 Checking Docker services status via docker-compose ps...")
    try:
        subprocess.run(["docker-compose", "ps"], check=True)
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"❌ Error checking status: {e}")

@env_app.command("logs")
def env_logs(service_name: Optional[str] = typer.Argument(None, help="Name of the service to show logs for (e.g., 'app', 'db').")):
    """Follows the logs of a specific service or all services."""
    command = ["docker-compose", "logs", "-f"]
    if service_name:
        print(f"📄 Following logs for service '{service_name}'...")
        command.append(service_name)
    else:
        print("📄 Following logs for all services...")

    try:
        subprocess.run(command, check=True)
    except KeyboardInterrupt:
        print("\n🛑 Stopped following logs.")
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"❌ Error getting logs: {e}")

@env_app.command("rebuild")
def env_rebuild():
    """Forces a rebuild of the Docker images without starting them."""
    print("🛠️ Forcing rebuild of Docker images via docker-compose build --no-cache...")
    try:
        subprocess.run(["docker-compose", "build", "--no-cache"], check=True)
        print("✅ Images rebuilt successfully.")
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"❌ Error rebuilding images: {e}")
