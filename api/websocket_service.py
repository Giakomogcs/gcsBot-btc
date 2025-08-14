import asyncio
import os
import json
from aiohttp import web
from jules_bot.utils.config_manager import ConfigManager
from jules_bot.database.postgres_manager import PostgresManager

async def query_postgres(db_manager: PostgresManager, table_name: str, time_range: str = "-1h"):
    """Queries PostgreSQL for data points within a specified time range."""
    try:
        # This is a simplified example. A real implementation would need to parse the time_range
        # and construct a proper SQL query.
        data = db_manager.get_price_data(table_name, start_date=time_range)
        if not data.empty:
            return data.to_dict(orient='records')
        return None
    except Exception as e:
        print(f"Error querying PostgreSQL: {e}")
        return None

async def data_websocket_handler(request):
    """Handles WebSocket connections for streaming PostgreSQL data."""
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    print(f"WebSocket connection for data streaming established: {request.path}")

    config_manager = ConfigManager()
    db_config = config_manager.get_db_config('POSTGRES')
    api_config = config_manager.get_section('API')
    db_manager = PostgresManager(config=db_config)

    # Extract table_name from URL path
    table_name = request.match_info.get('table_name', 'price_history')

    # Extract time_range and update_interval from query parameters
    time_range = request.query.get('time_range', '-1h')
    update_interval = int(api_config.get('update_interval', 5))

    while not ws.closed:
        try:
            data = await query_postgres(db_manager, table_name, time_range)
            if data:
                try:
                    await ws.send_str(json.dumps(data, default=str))
                except ConnectionResetError:
                    print("Client connection reset during send.")
                    break
                except Exception as e:
                    print(f"Error sending data over WebSocket: {e}")
                    break # Break loop on send error
            else:
                print(f"No data found for table '{table_name}' for time range '{time_range}'.")

        except Exception as e:
            print(f"Unhandled error in data_websocket_handler loop: {e}")
            break # Break loop on unhandled error

        await asyncio.sleep(update_interval)

    print(f"WebSocket connection for data streaming closed: {request.path}")
    return ws