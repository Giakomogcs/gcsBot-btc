import subprocess
import os
import sys
import time
import json

# --- Constants ---
TRADING_STATUS_FILE = os.path.join("logs", "trading_status.json")
OPTIMIZER_STATUS_FILE = os.path.join("logs", "optimizer_status.json")

# --- Helper Functions ---
def print_color(text, color="green"):
    """Prints text in color."""
    colors = {"green": "\033[92m", "yellow": "\033[93m", "red": "\033[91m", "blue": "\033[94m", "end": "\033[0m"}
    print(f"{colors.get(color, colors['green'])}{text}{colors['end']}")

def run_command(command, shell=True, capture_output=False, check=False):
    """Executes a shell command."""
    print_color(f"\n> Executing: {command}", "blue")
    try:
        if capture_output:
            return subprocess.run(command, shell=shell, capture_output=True, text=True, check=check, encoding='utf-8')
        else:
            process = subprocess.Popen(command, shell=shell, text=True, stdout=sys.stdout, stderr=sys.stderr)
            process.wait()
            if check and process.returncode != 0:
                raise subprocess.CalledProcessError(process.returncode, command)
            return process
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print_color(f"ERROR executing command: {command}\n{e}", "red")
        sys.exit(1)

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
    """Builds and starts the Docker services."""
    check_docker_running()
    print_color("--- Building Docker images (this may take a while)...", "yellow")
    run_command("docker compose build", check=True)
    print_color("--- Starting services in the background...", "yellow")
    run_command("docker compose up -d", check=True)
    print_color("--- Environment is ready! ---", "green")

def start_services():
    """Starts the Docker services."""
    check_docker_running()
    print_color("--- Starting services...", "yellow")
    run_command("docker compose up -d", check=True)

def stop_services():
    """Stops the Docker services."""
    check_docker_running()
    print_color("--- Stopping services...", "yellow")
    run_command("docker compose down", check=True)

def reset_db():
    """Stops the services and resets the database volume."""
    check_docker_running()
    print_color("--- STOPPING AND RESETTING DOCKER ENVIRONMENT ---", "red")
    run_command("docker compose down", check=True)
    print_color("--- REMOVING OLD INFLUXDB DATA VOLUME ---", "red")
    run_command("docker volume rm gcsbot-btc_influxdb_data", check=True)
    print_color("--- Reset complete. Use 'start-services' to begin again. ---", "green")

def run_script_in_container(script_path, *args):
    """Generic function to run a Python script inside the 'app' container."""
    check_docker_running()
    command = f"docker compose exec app python {script_path} {' '.join(args)}"
    run_command(command)

def show_display(status_file, dashboard_func, name):
    """Generic function to show a dashboard by reading a status file."""
    result = run_command("docker compose ps -q app", capture_output=True)
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
    if len(sys.argv) < 2:
        print_color("GCS-Bot - Control Panel", "yellow")
        print("---------------------------")
        print("\nUsage: python3 run.py [command]\n")
        print("Environment Management:")
        print("  setup           - Builds and starts the Docker environment for the first time.")
        print("  start-services  - Starts the Docker containers (app, db).")
        print("  stop-services   - Stops the Docker containers.")
        print("  reset-db        - DANGER! Stops and erases the database.")
        print("\nBot Operations:")
        print("  trade           - Starts the bot in live trading mode.")
        print("  test            - Starts the bot in test mode (live data, testnet wallet).")
        print("  backtest        - Runs a backtest with the current models.")
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
    args = sys.argv[2:]

    if command == "setup": setup()
    elif command == "start-services": start_services()
    elif command == "stop-services": stop_services()
    elif command == "reset-db": reset_db()
    elif command == "trade": run_script_in_container("main.py", "trade")
    elif command == "test": run_script_in_container("main.py", "test")
    elif command == "backtest": run_script_in_container("scripts/run_backtest.py")
    elif command == "optimize": run_script_in_container("scripts/run_optimizer.py")
    elif command == "update-db": run_script_in_container("scripts/data_pipeline.py")
    elif command == "clean-master": run_script_in_container("scripts/db_utils.py", "features_master_table")
    elif command == "reset-trades": run_script_in_container("scripts/db_utils.py", "trades")
    elif command == "reset-sentiment": run_script_in_container("scripts/db_utils.py", "sentiment_fear_and_greed")
    elif command == "show-trading":
        from gcs_bot.core.display_manager import display_trading_dashboard
        show_display(TRADING_STATUS_FILE, display_trading_dashboard, "Trading Bot")
    elif command == "show-optimizer":
        from gcs_bot.core.display_manager import display_optimization_dashboard
        show_display(OPTIMIZER_STATUS_FILE, display_optimization_dashboard, "Optimizer")
    elif command == "logs": run_command("docker compose logs -f app")
    elif command == "analyze": run_script_in_container("scripts/analyze_results.py")
    elif command == "analyze-decision": run_script_in_container("scripts/analyze_decision.py", *args)
    elif command == "run-tests": run_script_in_container("pytest")
    else:
        print_color(f"Command '{command}' not recognized.", "red")

if __name__ == "__main__":
    main()