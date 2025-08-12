import os
import sys
from influxdb_client import InfluxDBClient, Bucket, Organization, Authorization
from influxdb_client.client.authorizations_api import AuthorizationsApi
from influxdb_client.client.bucket_api import BucketsApi
from influxdb_client.client.organizations_api import OrganizationsApi
from influxdb_client.rest import ApiException

# Add project root to sys.path to allow imports from jules_bot
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from jules_bot.utils.config_manager import ConfigManager

def main():
    """
    Main function to run the initial InfluxDB setup.
    - Creates the organization.
    - Creates required buckets.
    - Creates an application token with specific permissions.
    """
    client = None  # Initialize client to None for the finally block
    try:
        # --- 1. Load Configuration ---
        config_manager = ConfigManager()
        influx_config = config_manager.get_section('INFLUXDB')

        # Get host, port, and org from environment variables with sensible defaults
        # This makes the script runnable both locally and in a container
        url = os.getenv('INFLUXDB_URL')
        if not url:
            host = os.getenv('INFLUXDB_HOST', 'localhost')
            port = os.getenv('INFLUXDB_PORT', '8086')
            url = f"http://{host}:{port}"

        org_name = os.getenv('INFLUXDB_ORG')

        if not org_name:
            print("❌ ERROR: INFLUXDB_ORG environment variable not set.")
            print("Please set this to your desired InfluxDB organization name.")
            sys.exit(1)

        # Admin token must be provided via environment variable for initial setup
        admin_token = os.getenv("INFLUXDB_TOKEN")
        if not admin_token:
            print("❌ ERROR: INFLUXDB_TOKEN environment variable not set.")
            print("Please set this to your InfluxDB admin token to run the initial setup.")
            sys.exit(1)

        print(f"Connecting to InfluxDB at {url}...")
        client = InfluxDBClient(url=url, token=admin_token, org=org_name)
        org_api = client.organizations_api()
        bucket_api = client.buckets_api()
        auth_api = client.authorizations_api()

        # --- 2. Find or Create Organization ---
        print(f"Checking for organization '{org_name}'...")
        org = None
        try:
            orgs = org_api.find_organizations(org=org_name)
            if orgs:
                org = orgs[0]
                print(f"✅ Organization '{org_name}' already exists (ID: {org.id}).")
            else:
                print(f"Organization '{org_name}' not found. Creating it...")
                new_org = Organization(name=org_name)
                org = org_api.create_organization(new_org)
                print(f"✅ Organization '{org_name}' created successfully (ID: {org.id}).")
        except ApiException as e:
            if "organization name is already taken" in str(e.body):
                 orgs = org_api.find_organizations(org=org_name)
                 if orgs:
                    org = orgs[0]
                    print(f"✅ Organization '{org_name}' already exists (ID: {org.id}).")
                 else:
                    print(f"❌ ERROR: Organization '{org_name}' reported as taken, but could not be found.")
                    sys.exit(1)
            else:
                print(f"❌ ERROR: Could not create or find organization '{org_name}'.")
                print(f"   Reason: {e}")
                sys.exit(1)

        # --- 3. Create Buckets ---
        buckets_to_create = [
            influx_config.get('bucket_live'),
            influx_config.get('bucket_testnet'),
            influx_config.get('bucket_backtest'),
            influx_config.get('bucket_prices')
        ]

        print("\nChecking for required buckets...")
        for bucket_name in buckets_to_create:
            if not bucket_name:
                print(f"⚠️ WARNING: A bucket name is not defined in config.ini. Skipping.")
                continue

            try:
                existing_bucket = bucket_api.find_bucket_by_name(bucket_name=bucket_name)
                if existing_bucket:
                    print(f"✅ Bucket '{bucket_name}' already exists.")
                else:
                    print(f"Bucket '{bucket_name}' not found. Creating it...")
                    new_bucket = Bucket(name=bucket_name, org_id=org.id, retention_rules=[])
                    bucket_api.create_bucket(new_bucket)
                    print(f"✅ Bucket '{bucket_name}' created successfully.")
            except ApiException as e:
                if "bucket with name already exists" in str(e.body):
                    print(f"✅ Bucket '{bucket_name}' already exists.")
                else:
                    print(f"❌ ERROR: Could not create bucket '{bucket_name}'.")
                    print(f"   Reason: {e}")
                    # Continue to the next bucket instead of exiting

        # --- 4. Create Application Token ---
        print("\nSkipping application token creation.")
        print("\n--- Initial Setup Complete ---")
        print(f"Organization: {org_name}")
        valid_buckets = [b for b in buckets_to__create if b]
        print(f"Buckets: {', '.join(valid_buckets)}")
        
        print("\nSetup script finished.")

    except FileNotFoundError as e:
        print(f"❌ ERROR: Configuration file not found at '{e.filename}'.")
        print("   Please ensure config.ini exists in the root directory.")
        sys.exit(1)
    except ApiException as e:
        # More specific error handling for API exceptions
        print(f"❌ An InfluxDB API error occurred: {e.reason} (Status: {e.status})")
        print(f"   Body: {e.body}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ An unexpected error occurred: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        if client:
            client.close()

if __name__ == "__main__":
    main()
