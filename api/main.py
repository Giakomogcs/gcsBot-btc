import asyncio
import os
import sys
import json
from aiohttp import web

# Add project root to sys.path to allow imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from api.command_executor import run_command_in_container
from jules_bot.utils.config_manager import ConfigManager
from jules_bot.database.postgres_manager import PostgresManager

async def trade_handler(request):
    print("Received HTTP request to start TRADE bot.")
    success, output = await run_command_in_container(
                                               command=["jules_bot/main.py"],
                                               env_vars={"BOT_MODE": "trade"})
    if success:
        return web.Response(text=f"TRADE bot started successfully.\nOutput:\n{output}")
    else:
        return web.Response(text=f"Failed to start TRADE bot.\nOutput:\n{output}", status=500)

async def test_handler(request):
    print("Received HTTP request to start TEST bot.")
    success, output = await run_command_in_container(
                                               command=["jules_bot/main.py"],
                                               env_vars={"BOT_MODE": "test"})
    if success:
        return web.Response(text=f"TEST bot started successfully.\nOutput:\n{output}")
    else:
        return web.Response(text=f"Failed to start TEST bot.\nOutput:\n{output}", status=500)

async def backtest_handler(request):
    print("Received HTTP request to start BACKTEST.")
    data = await request.json()
    days = data.get('days', 30) # Default to 30 days if not provided

    # Step 1: Prepare data
    print(f"--- Step 1 of 2: Preparing data for {days} days ---")
    success_prepare, output_prepare = await run_command_in_container(
                                                               command=["scripts/prepare_backtest_data.py", str(days)])
    if not success_prepare:
        return web.Response(text=f"Failed to prepare backtest data.\nOutput:\n{output_prepare}", status=500)

    # Step 2: Run backtest
    print(f"--- Step 2 of 2: Running backtest for {days} days ---")
    success_run, output_run = await run_command_in_container(
                                                      command=["scripts/run_backtest.py", str(days)])
    if success_run:
        return web.Response(text=f"Backtest completed successfully.\nPreparation Output:\n{output_prepare}\n\nRun Output:\n{output_run}")
    else:
        return web.Response(text=f"Failed to run backtest.\nPreparation Output:\n{output_prepare}\n\nRun Output:\n{output_run}", status=500)

async def command_websocket_handler(request):
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    print("DEBUG: WebSocket connection for command logs established.")

    async for msg in ws:
        if msg.type == web.WSMsgType.TEXT:
            try:
                data = json.loads(msg.data)
                command_type = data.get('command')
                print(f"DEBUG: Received command: {command_type}")

                if command_type == "trade":
                    print(f"DEBUG: Calling run_command_in_container for TRADE. ws is not None: {ws is not None}")
                    await run_command_in_container(command=["jules_bot/main.py"], env_vars={"BOT_MODE": "trade"}, ws=ws)
                elif command_type == "test":
                    print(f"DEBUG: Calling run_command_in_container for TEST. ws is not None: {ws is not None}")
                    await run_command_in_container(command=["jules_bot/main.py"], env_vars={"BOT_MODE": "test"}, ws=ws)
                elif command_type == "backtest":
                    days = data.get('days', 30)
                    print(f"DEBUG: Calling run_command_in_container for BACKTEST. ws is not None: {ws is not None}")
                    # Step 1: Prepare data
                    await ws.send_str(f"--- Step 1 of 2: Preparing data for {days} days ---")
                    success_prepare, _ = await run_command_in_container(command=["scripts/prepare_backtest_data.py", str(days)], ws=ws)
                    if not success_prepare:
                        await ws.send_str("❌ Backtest data preparation failed.")
                        continue
                    # Step 2: Run backtest
                    await ws.send_str(f"--- Step 2 of 2: Running backtest for {days} days ---")
                    await run_command_in_container(command=["scripts/run_backtest.py", str(days)], ws=ws)
                else:
                    await ws.send_str("Unknown command.")
            except json.JSONDecodeError:
                await ws.send_str("Invalid JSON format.")
            except Exception as e:
                await ws.send_str(f"Error processing command: {e}")
        elif msg.type == web.WSMsgType.ERROR:
            print(f"DEBUG: WebSocket connection closed with exception: {ws.exception()}")
    print("DEBUG: WebSocket connection for command logs closed.")
    return ws

async def get_trades_handler(request):
    config_manager = ConfigManager()
    db_config = config_manager.get_db_config('POSTGRES')
    db_manager = PostgresManager(config=db_config)

    environment = request.query.get('environment')
    start_date = request.query.get('start_date')
    end_date = request.query.get('end_date')

    if not all([environment, start_date, end_date]):
        return web.Response(text="'environment', 'start_date', and 'end_date' are required query parameters.", status=400)

    data = db_manager.get_trades(environment, start_date, end_date)

    if not data.empty:
        return web.json_response(json.loads(data.to_json(orient='records', date_format='iso')))
    else:
        return web.Response(text=f"No trades found for environment '{environment}' in the given time range.", status=404)

async def get_price_history_handler(request):
    config_manager = ConfigManager()
    db_config = config_manager.get_db_config('POSTGRES')
    db_manager = PostgresManager(config=db_config)

    start_date = request.query.get('start_date')
    end_date = request.query.get('end_date')

    if not all([start_date, end_date]):
        return web.Response(text="'start_date' and 'end_date' are required query parameters.", status=400)

    data = db_manager.get_price_history(start_date, end_date)

    if not data.empty:
        return web.json_response(json.loads(data.to_json(orient='records', date_format='iso')))
    else:
        return web.Response(text="No price history found for the given time range.", status=404)

async def main():
    """
    Main function to set up and run the aiohttp web server.
    """
    app = web.Application()
    app.router.add_get('/ws/command_logs', command_websocket_handler) # For command execution logs
    app.router.add_post('/run/trade', trade_handler)
    app.router.add_post('/run/test', test_handler)
    app.router.add_post('/run/backtest', backtest_handler)
    app.router.add_get('/data/trades', get_trades_handler)
    app.router.add_get('/data/price_history', get_price_history_handler)

    config_manager = ConfigManager()
    api_config = config_manager.get_section('API')
    port = int(api_config.get('port', 8765))

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)

    print(f"🚀 API server starting on http://0.0.0.0:{port}")
    await site.start()

    # Keep the server running
    await asyncio.Event().wait()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("🛑 Server stopped manually.")
