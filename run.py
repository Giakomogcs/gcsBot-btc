import typer
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
