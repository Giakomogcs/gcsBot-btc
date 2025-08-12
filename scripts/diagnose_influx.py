import os
import sys
from influxdb_client import InfluxDBClient
from influxdb_client.client.exceptions import InfluxDBError

# Add project root to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from jules_bot.utils.config_manager import ConfigManager

def get_influxdb_client():
    """Initializes and returns an InfluxDB client using the project's configuration."""
    try:
        # Assuming config.ini is in the root directory
        config_manager = ConfigManager()
        db_config = config_manager.get_db_config()

        client = InfluxDBClient(
            url=db_config.get("url"),
            token=db_config.get("token"),
            org=db_config.get("org")
        )
        print("Successfully created InfluxDB client.")
        return client
    except Exception as e:
        print(f"Error creating InfluxDB client: {e}")
        return None

def list_buckets(client: InfluxDBClient):
    """Lists all buckets in the InfluxDB instance."""
    if not client:
        print("InfluxDB client is not available.")
        return None
    try:
        buckets_api = client.buckets_api()
        buckets = buckets_api.find_buckets().buckets
        print("\n--- Bucket Discovery ---")
        if buckets:
            print("Available buckets:")
            for bucket in buckets:
                print(f"- {bucket.name} (ID: {bucket.id})")
            return buckets
        else:
            print("No buckets found.")
            return []
    except InfluxDBError as e:
        print(f"Error listing buckets: {e}")
        return None

def list_measurements(client: InfluxDBClient, bucket_name: str):
    """Lists all measurements in a specific bucket."""
    if not client:
        print("InfluxDB client is not available.")
        return
    try:
        query_api = client.query_api()
        query = f'''
        import "influxdata/influxdb/schema"
        schema.measurements(bucket: "{bucket_name}")
        '''
        print(f"\n--- Measurements in '{bucket_name}' ---")
        tables = query_api.query(query)
        measurements = [row.values.get('_value') for table in tables for row in table.records]
        if measurements:
            for measurement in measurements:
                print(f"- {measurement}")
        else:
            print("No measurements found.")
    except InfluxDBError as e:
        print(f"Error listing measurements: {e}")


def get_schema(client: InfluxDBClient, bucket_name: str, measurement_name: str):
    """Gets the schema for a specific measurement."""
    if not client:
        print("InfluxDB client is not available.")
        return
    try:
        query_api = client.query_api()
        print(f"\n--- Schema for '{measurement_name}' in '{bucket_name}' ---")

        # Get tags
        tag_keys_query = f'''
        import "influxdata/influxdb/schema"
        schema.measurementTagKeys(bucket: "{bucket_name}", measurement: "{measurement_name}")
        '''
        tag_tables = query_api.query(tag_keys_query)
        tags = [row.values.get('_value') for table in tag_tables for row in table.records]
        if tags:
            print("Tags:")
            for tag in tags:
                print(f"- {tag}")
        else:
            print("No tags found.")

        # Get fields and their types
        field_keys_query = f'''
        import "influxdata/influxdb/schema"
        schema.measurementFieldKeys(bucket: "{bucket_name}", measurement: "{measurement_name}")
        '''
        field_tables = query_api.query(field_keys_query)
        fields = {}
        for table in field_tables:
            for row in table.records:
                field_name = row.values.get('_value')
                # This is a hacky way to get the type, but it's the only way with the python client
                type_query = f'''
                from(bucket: "{bucket_name}")
                  |> range(start: -100y)
                  |> filter(fn: (r) => r._measurement == "{measurement_name}" and r._field == "{field_name}")
                  |> first()
                  |> keep(columns: ["_value"])
                '''
                type_tables = query_api.query(type_query)
                field_type = "unknown"
                if type_tables and type_tables[0].records:
                    value = type_tables[0].records[0].get_value()
                    field_type = type(value).__name__
                fields[field_name] = field_type

        if fields:
            print("\nFields:")
            for field, ftype in fields.items():
                print(f"- {field}: {ftype}")
        else:
            print("No fields found.")

    except InfluxDBError as e:
        print(f"Error getting schema: {e}")


def find_mixed_type_field(client: InfluxDBClient, bucket_name: str, measurement_name: str):
    """Finds a field with mixed float and string types in a measurement."""
    if not client:
        print("InfluxDB client is not available.")
        return
    try:
        query_api = client.query_api()
        print(f"\n--- Checking for mixed types in '{measurement_name}' ---")

        # This query is designed to find a field that has both float and string values.
        # It's not possible to do this directly in a single Flux query.
        # We have to get all the data and check it in python.

        query = f'''
        from(bucket: "{bucket_name}")
            |> range(start: 0)
            |> filter(fn: (r) => r._measurement == "{measurement_name}")
        '''
        tables = query_api.query(query)

        field_types = {}

        for table in tables:
            for record in table.records:
                field = record.get_field()
                value = record.get_value()
                value_type = type(value).__name__

                if field not in field_types:
                    field_types[field] = set()
                field_types[field].add(value_type)

        mixed_fields = []
        for field, types in field_types.items():
            if len(types) > 1:
                print(f"Found mixed types in field '{field}': {types}")
                mixed_fields.append(field)

        if not mixed_fields:
            print("No mixed type fields found.")

    except InfluxDBError as e:
        print(f"Error finding mixed type field: {e}")


def main():
    """Main function to run the diagnostics."""
    client = get_influxdb_client()
    if client:
        buckets = list_buckets(client)
        if buckets:
            # Assuming the trading bucket is the one with "trades" in the name
            trading_bucket = None
            for b in buckets:
                if "trades" in b.name:
                    trading_bucket = b.name
                    break

            if trading_bucket:
                list_measurements(client, trading_bucket)
                get_schema(client, trading_bucket, "trades")
                find_mixed_type_field(client, trading_bucket, "trades")
            else:
                print("\nCould not determine the trading bucket.")

        client.close()

if __name__ == "__main__":
    main()
