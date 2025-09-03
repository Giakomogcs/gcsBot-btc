import typer
import requests
from typing_extensions import Annotated
from jules_bot.utils import process_manager


def main(
    usd_amount: Annotated[float, typer.Argument(
        help="The amount in USD to buy.",
        show_default=False,
    )],
    bot_name: Annotated[str, typer.Option(
        "--bot-name", "-n",
        help="The name of the bot to send the command to. Defaults to the BOT_NAME environment variable.",
        envvar="BOT_NAME",
        show_default=False,
    )],
):
    """
    Sends a 'force_buy' command to the running bot via its API.
    """
    bot = process_manager.get_bot_by_name(bot_name)
    if not bot:
        print(f"❌ Error: Bot '{bot_name}' not found or is not running.")
        print("   Make sure the bot is started and check the name for typos.")
        raise typer.Exit(code=1)

    if usd_amount < 1.0:
        print("❌ Error: The amount to buy must be at least 1.0 USD.")
        raise typer.Exit(code=1)

    base_url = f"http://host.docker.internal:{bot.host_port}/api"
    endpoint = f"{base_url}/force_buy"
    payload = {"amount_usd": usd_amount}

    print(f"▶️ Sending force buy command for ${usd_amount:.2f} to {endpoint}...")

    try:
        response = requests.post(endpoint, json=payload, timeout=10)

        if response.status_code == 200:
            print("✅ Success! Bot executed the buy command.")
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
