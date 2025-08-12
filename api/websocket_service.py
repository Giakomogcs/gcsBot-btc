import asyncio
import os
import json
from aiohttp import web
from influxdb_client.client.influxdb_client_async import InfluxDBClientAsync
from influxdb_client.client.exceptions import InfluxDBError

# Assuming config_manager is accessible
from jules_bot.utils.config_manager import ConfigManager

async def query_influxdb(client: InfluxDBClientAsync, bucket: str, measurement: str, time_range: str = "-1h"):
    """Queries InfluxDB for data points within a specified time range."""
    query_api = client.query_api()
    query = f'''
    from(bucket: "{bucket}")
      |> range(start: {time_range})
      |> filter(fn: (r) => r._measurement == "{measurement}")
    '''
    try:
        tables = await query_api.query(query)
        data = []
        for table in tables:
            for record in table.records:
                data.append(record.values)
        return data
    except InfluxDBError as e:
        print(f"Error querying InfluxDB (InfluxDBError): {e}")
        return None
    except Exception as e:
        print(f"Error querying InfluxDB (General Exception): {e}")
        return None

async def data_websocket_handler(request):
    """Handles WebSocket connections for streaming InfluxDB data."""
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    print(f"WebSocket connection for data streaming established: {request.path}")

    config_manager = ConfigManager()
    influx_config = config_manager.get_section('INFLUXDB')
    api_config = config_manager.get_section('API')

    host = os.getenv('INFLUXDB_HOST', 'localhost')
    port = os.getenv('INFLUXDB_PORT', '8086')
    token = os.getenv('INFLUXDB_TOKEN')
    org = os.getenv('INFLUXDB_ORG')
    
    # Extract measurement from URL path
    measurement = request.match_info.get('measurement', api_config.get('measurement', 'price_data'))
    bucket = influx_config.get('bucket_prices', 'prices') # Default bucket

    # Extract time_range and update_interval from query parameters
    time_range = request.query.get('time_range', '-1h')
    update_interval = int(api_config.get('update_interval', 5))

    url = f"http://{host}:{port}"

    async with InfluxDBClientAsync(url=url, token=token, org=org) as client:
        while not ws.closed:
            try:
                data = await query_influxdb(client, bucket, measurement, time_range)
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
                    print(f"No data found for measurement '{measurement}' in bucket '{bucket}' for time range '{time_range}'.")

            except Exception as e:
                print(f"Unhandled error in data_websocket_handler loop: {e}")
                break # Break loop on unhandled error
            
            await asyncio.sleep(update_interval)

    print(f"WebSocket connection for data streaming closed: {request.path}")
    return ws