import typer
import requests
from typing_extensions import Annotated

API_PORT = 8766  # This should match the port in trading_bot.py
BASE_URL = f"http://localhost:{API_PORT}/api"

def main(
    usd_amount: Annotated[float, typer.Argument(
        help="The amount in USD to buy.",
        min=1.0,
        show_default=False
    )],
):
    """
    Sends a 'force_buy' command to the running bot via its API.
    """
    endpoint = f"{BASE_URL}/force_buy"
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
