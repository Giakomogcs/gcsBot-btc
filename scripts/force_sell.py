import typer
import requests
from typing_extensions import Annotated
from jules_bot.utils import process_manager


def main(
    trade_id: Annotated[str, typer.Argument(
        help="The unique ID of the trade to sell.",
        show_default=False
    )],
    percentage: Annotated[str, typer.Argument(
        help="The percentage of the position to sell (e.g., '100' for 100%).",
        show_default=False
    )],
    bot_name: Annotated[str, typer.Option(
        "--bot-name", "-n",
        help="The name of the bot to send the command to. Defaults to the BOT_NAME environment variable.",
        envvar="BOT_NAME",
        show_default=False,
    )],
):
    """
    Sends a 'force_sell' command to the running bot via its API.
    """
    bot = process_manager.get_bot_by_name(bot_name)
    if not bot:
        print(f"❌ Error: Bot '{bot_name}' not found or is not running.")
        print("   Make sure the bot is started and check the name for typos.")
        raise typer.Exit(code=1)

    try:
        p = float(percentage)
        if not 1.0 <= p <= 100.0:
            print("❌ Error: The percentage must be between 1.0 and 100.0.")
            raise typer.Exit(code=1)
    except ValueError:
        print(f"❌ Error: Invalid number format '{percentage}'.")
        raise typer.Exit(code=1)

    base_url = f"http://localhost:{bot.host_port}/api"
    endpoint = f"{base_url}/force_sell"
    payload = {"trade_id": trade_id, "percentage": percentage}

    print(f"▶️ Sending force sell command for {percentage}% of trade {trade_id} to {endpoint}...")

    try:
        response = requests.post(endpoint, json=payload, timeout=10)

        if response.status_code == 200:
            print("✅ Success! Bot executed the sell command.")
            print("   Response:", response.json())
        elif response.status_code == 400:
            print("❌ Bad Request: The bot rejected the command.")
            print("   Reason:", response.json().get("detail"))
        else:
            print(f"❌ Error: Received status code {response.status_code}")
            try:
                print("   Response:", response.json())
            except requests.exceptions.JSONDecodeError:
                print("   Response body:", response.text)

    except requests.exceptions.RequestException as e:
        print(f"❌ Failed to connect to the bot's API at {endpoint}.")
        print(f"   Is the bot running? Details: {e}")
        raise typer.Exit(code=1)

if __name__ == "__main__":
    typer.run(main)