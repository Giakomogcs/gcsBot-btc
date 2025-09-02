import typer
import requests
from typing_extensions import Annotated

API_PORT = 8766  # This should match the port in trading_bot.py
BASE_URL = f"http://localhost:{API_PORT}/api"

def main(
    trade_id: Annotated[str, typer.Argument(
        help="The unique ID of the trade to sell.",
        show_default=False
    )],
    percentage: Annotated[float, typer.Argument(
        help="The percentage of the position to sell (e.g., 100 for 100%).",
        min=1.0,
        max=100.0,
        show_default=False
    )],
):
    """
    Sends a 'force_sell' command to the running bot via its API.
    """
    endpoint = f"{BASE_URL}/force_sell"
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