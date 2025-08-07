import subprocess
import os
import sys
import time
import json
import typer
from jules_bot.bot.trading_bot import TradingBot
from jules_bot.utils.config_manager import settings

# --- Typer App for Bot Commands ---
app = typer.Typer()

def setup_bot(mode: str) -> TradingBot:
    """A centralized function to initialize all necessary components for the bot."""
    print(f"--- Initializing Bot in {mode.upper()} Mode ---")
    # ConfigManager is not needed here because settings are loaded globally
    return TradingBot(mode=mode)

def run_with_graceful_shutdown(bot: TradingBot):
    """Wrapper to run the bot and ensure shutdown is always called."""
    try:
        bot.run()
    except Exception as e:
        print(f"\n[FATAL ERROR] An unexpected error occurred: {e}")
    finally:
        if bot:
            bot.shutdown()

PID_FILE = "/tmp/bot.pid"

@app.command()
def trade():
    """
    Starts the trading bot as a background daemon process.
    """
    if os.name != 'posix':
        print("This command is only available on Unix-like systems (Linux, macOS).")
        return

    if os.path.exists(PID_FILE):
        print("Bot is already running. Use 'stop' command first.")
        return

    # The 'daemonize' process: launch a child process and let the parent exit.
    try:
        pid = os.fork()
        if pid > 0:
            # This is the parent process. We exit immediately.
            print(f"Bot started as a background process with PID: {pid}")
            sys.exit(0)
    except OSError as e:
        sys.stderr.write(f"fork #1 failed: {e}\n")
        sys.exit(1)

    # This is now the child process.
    # It needs to set up its own environment.
    os.chdir("/") # Change to root to avoid holding onto directories
    os.setsid()
    os.umask(0)

    # Second fork for complete detachment
    try:
        pid = os.fork()
        if pid > 0:
            sys.exit(0)
    except OSError as e:
        sys.stderr.write(f"fork #2 failed: {e}\n")
        sys.exit(1)

    # Write the PID file
    with open(PID_FILE, "w+") as f:
        f.write(str(os.getpid()))

    # Now, finally, run the bot's main logic
    from jules_bot.bot.trading_bot import TradingBot
    bot = TradingBot(mode="trade")
    bot.run() # The main loop from Phase 1

@app.command()
def stop():
    """Stops the running background bot process."""
    if os.name != 'posix':
        print("This command is only available on Unix-like systems (Linux, macOS).")
        return

    if not os.path.exists(PID_FILE):
        print("Bot is not running.")
        return

    with open(PID_FILE) as f:
        pid = int(f.read())

    try:
        # Send the SIGTERM signal to trigger graceful shutdown
        os.kill(pid, signal.SIGTERM)
        print(f"Sent shutdown signal to bot process {pid}.")
    except ProcessLookupError:
        print(f"Process {pid} not found. It may have already stopped.")
    finally:
        os.remove(PID_FILE)

@app.command()
def show():
    """Launches the TUI to display the running bot's state."""
    if not os.path.exists(PID_FILE):
        print("Cannot show UI: Bot is not running. Use the 'trade' command to start it.")
        return

    from jules_bot.ui.app import JulesBotApp
    app = JulesBotApp()
    app.run()

@app.command()
def backtest():
    """Runs the bot in BACKTESTING mode."""
    bot = setup_bot(mode="backtest")
    run_with_graceful_shutdown(bot)

@app.command()
def test():
    """Runs the bot in paper trading (TEST) mode."""
    bot = setup_bot(mode="test")
    run_with_graceful_shutdown(bot)

# --- Constants ---
TRADING_STATUS_FILE = os.path.join("logs", "trading_status.json")
OPTIMIZER_STATUS_FILE = os.path.join("logs", "optimizer_status.json")

# --- Helper Functions ---
def print_color(text, color="green"):
    """Prints text in color."""
    colors = {"green": "\033[92m", "yellow": "\033[93m", "red": "\033[91m", "blue": "\033[94m", "end": "\033[0m"}
    print(f"{colors.get(color, colors['green'])}{text}{colors['end']}")

def run_command(command, shell=True, capture_output=False, check=False, env=None):
    """Executes a shell command, with better support for environment variables."""
    # Para comandos passados como lista de argumentos, shell=False é mais seguro.
    # Para strings simples, mantemos o comportamento original.
    use_shell = not isinstance(command, list)
    
    # Exibe o comando de forma legível
    display_command = ' '.join(command) if isinstance(command, list) else command
    print_color(f"\n> Executing: {display_command}", "blue")

    try:
        if capture_output:
            return subprocess.run(command, shell=use_shell, capture_output=True, text=True, check=check, encoding='utf-8', env=env)
        else:
            process = subprocess.Popen(command, shell=use_shell, text=True, stdout=sys.stdout, stderr=sys.stderr, env=env)
            process.wait()
            if check and process.returncode != 0:
                raise subprocess.CalledProcessError(process.returncode, command)
            return process
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print_color(f"ERROR executing command: {display_command}\n{e}", "red")
        sys.exit(1)

# The start_bot function is removed as the bot is now started with `docker-compose up`.

def check_docker_running():
    """Checks if Docker is running."""
    print_color("Verifying Docker status...", "yellow")
    try:
        run_command("docker info", capture_output=True, check=True)
        print_color("Docker is running.", "green")
    except (subprocess.CalledProcessError, FileNotFoundError):
        print_color("ERROR: Docker Desktop does not seem to be running.", "red")
        sys.exit(1)

# --- Docker-based Commands ---
def setup():
    """Builds and starts the Docker services, including initial data population."""
    check_docker_running()
    print_color("--- Building Docker images (this may take a while)...", "yellow")
    run_command("docker-compose build", check=True) # Alterado
    print_color("--- Starting services in the background (db, etc.)...", "yellow")
    run_command("docker-compose up -d", check=True) # Alterado

    print_color("--- Waiting for services to be ready before populating DB...", "yellow")
    time.sleep(10) # Dá um tempo para o InfluxDB iniciar completamente

    print_color("--- POPULATING DATABASE WITH INITIAL DATA (ETL Pipeline)...", "yellow")
    print_color("This is a one-time setup and may take several minutes...", "yellow")
    run_script_in_container("scripts/data_pipeline.py")

    print_color("--- ✅ Environment is ready! You can now start the bot. ---", "green")

def start_services():
    """Starts the Docker services."""
    check_docker_running()
    print_color("--- Starting services...", "yellow")
    run_command("docker-compose up -d", check=True) # Alterado

def start():
    """Starts the Docker services."""
    check_docker_running()
    print_color("--- Starting services...", "yellow")
    run_command("docker-compose up --build -d app", check=True) 

def stop_services():
    """Stops the Docker services."""
    check_docker_running()
    print_color("--- Stopping services...", "yellow")
    run_command("docker-compose down", check=True) # Alterado

def reset_db():
    """Stops the services and resets the database volume."""
    check_docker_running()
    print_color("--- STOPPING AND RESETTING DOCKER ENVIRONMENT ---", "red")
    run_command("docker-compose down", check=True) # Alterado
    print_color("--- REMOVING OLD INFLUXDB DATA VOLUME ---", "red")
    # Este comando 'docker volume' não precisa de alteração
    run_command("docker volume rm gcsbot-btc_influxdb_data", check=True)
    print_color("--- Reset complete. Use 'start-services' to begin again. ---", "green")

def run_script_in_container(script_path, *args):
    """Generic function to run a Python script inside the 'app' container."""
    check_docker_running()
    command = f"docker-compose exec app python {script_path} {' '.join(args)}" # Alterado
    run_command(command)


def show_display(status_file, dashboard_func, name):
    """Generic function to show a dashboard by reading a status file."""
    result = run_command("docker-compose ps -q app", capture_output=True) # Alterado
    if not result.stdout.strip():
        print_color(f"The '{name}' container 'app' is not running.", "red")
        return

    print_color(f"Showing {name} dashboard. Press CTRL+C to exit.", "green")
    try:
        while True:
            if os.path.exists(status_file):
                try:
                    with open(status_file, 'r') as f:
                        status_data = json.load(f)
                    os.system('cls' if os.name == 'nt' else 'clear')
                    dashboard_func(status_data)
                except (json.JSONDecodeError, KeyError) as e:
                    print(f"Waiting for a valid status file... Error: {e}")
            else:
                print(f"Waiting for {name} to start and create the status file...")
            time.sleep(2)
    except KeyboardInterrupt:
        print_color(f"\nDashboard for {name} terminated.", "yellow")

# --- Main Command-line Interface ---
def main():
    """Main CLI entry point."""
    if len(sys.argv) < 2 or sys.argv[1].lower() in ['--help', '-h']:
        print_color("GCS-Bot - Control Panel", "yellow")
        print("---------------------------")
        print("\nUsage: python3 run.py [command]\n")
        print("Environment Management:")
        print("  setup           - Builds and starts the Docker environment for the first time.")
        print("  start-services  - Starts the Docker containers (app, db).")
        print("  stop-services   - Stops the Docker containers.")
        print("  reset-db        - DANGER! Stops and erases the database.")
        print("\nBot Execution (Docker Override):")
        print("  trade           - Runs the bot in live trading mode.")
        print("  backtest        - Runs the bot in backtesting mode.")
        print("  test            - Runs the bot in paper trading (test) mode.")
        print("\nBot Operations (via docker-compose):")
        print("  optimize        - Runs the model optimization process.")
        print("  update-db       - Runs the ETL pipeline to update the database.")
        print("\nDatabase Utilities:")
        print("  clean-master    - Clears the 'features_master_table'.")
        print("  reset-trades    - Clears all trade records from the database.")
        print("  reset-sentiment - Clears all sentiment data from the database.")
        print("\nMonitoring & Analysis:")
        print("  show-trading    - Shows the live trading dashboard.")
        print("  show-optimizer  - Shows the optimizer dashboard.")
        print("  logs            - Shows the raw logs from the running application.")
        print("  analyze         - Analyzes the results of the last backtest run.")
        print("  analyze-decision <model> \"<datetime>\" - Analyzes a specific model's decision.")
        print("  run-tests       - Runs the automated test suite (pytest).")
        return

    command = sys.argv[1].lower()

    # Check if the command is a bot command
    if command in ["trade", "backtest", "test"]:
        # Pass control to the Typer app
        # Typer automatically uses sys.argv, so we just call the app.
        app()
        return

    # Handle original environment commands
    args = sys.argv[2:]
    if command == "setup": setup()
    elif command == "start-services": start_services()
    elif command == "start": start()
    elif command == "stop": stop_services()
    elif command == "reset-db": reset_db()
    elif command == "optimize": run_script_in_container("scripts/run_optimizer.py")
    elif command == "update-db": run_script_in_container("scripts/data_pipeline.py")
    elif command == "clean-master": run_script_in_container("scripts/db_utils.py", "features_master_table")
    elif command == "reset-trades": run_script_in_container("scripts/db_utils.py", "trades")
    elif command == "reset-sentiment": run_script_in_container("scripts/db_utils.py", "sentiment_fear_and_greed")
    elif command == "show-trading":
        from jules_bot.ui.display_manager import display_trading_dashboard
        show_display(TRADING_STATUS_FILE, display_trading_dashboard, "Trading Bot")
    elif command == "show-optimizer":
        from jules_bot.ui.display_manager import display_optimization_dashboard
        show_display(OPTIMIZER_STATUS_FILE, display_optimization_dashboard, "Optimizer")
    elif command == "logs": run_command("docker-compose logs -f app") # Alterado
    elif command == "analyze": run_script_in_container("scripts/analyze_results.py")
    elif command == "analyze-decision": run_script_in_container("scripts/analyze_decision.py", *args)
    elif command == "run-tests": run_script_in_container("pytest")
    else:
        print_color(f"Command '{command}' not recognized.", "red")

if __name__ == "__main__":
    main()