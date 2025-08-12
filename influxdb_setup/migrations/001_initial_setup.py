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
        host = os.getenv('INFLUXDB_HOST', 'localhost')
        port = os.getenv('INFLUXDB_PORT', '8086')
        org_name = os.getenv('INFLUXDB_ORG')

        if not org_name:
            print("❌ ERROR: INFLUXDB_ORG environment variable not set.")
            print("Please set this to your desired InfluxDB organization name.")
            sys.exit(1)

        url = f"http://{host}:{port}"

        # Admin token must be provided via environment variable for initial setup
        admin_token = os.getenv("INFLUXDB_TOKEN")
        if not admin_token:
            print("❌ ERROR: INFLUXDB_TOKEN environment variable not set.")
            print("Please set this to your InfluxDB admin token to run the initial setup.")
            sys.exit(1)

        print(f"Connecting to InfluxDB at {url}...")
        client = InfluxDBClient(url=url, token=admin_token)
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
                existing_bucket = bucket_api.find_bucket_by_name(bucket_name=bucket_name, org_id=org.id)
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
        app_token_description = "JulesBot Application Token"
        print(f"\nChecking for application token: '{app_token_description}'...")

        permissions = [
            {"action": "read", "resource": {"type": "buckets", "orgID": org.id}},
            {"action": "write", "resource": {"type": "buckets", "orgID": org.id, "name": influx_config.get('bucket_live')}},
            {"action": "write", "resource": {"type": "buckets", "orgID": org.id, "name": influx_config.get('bucket_testnet')}},
            {"action": "write", "resource": {"type": "buckets", "orgID": org.id, "name": influx_config.get('bucket_backtest')}},
            {"action": "write", "resource": {"type": "buckets", "orgID": org.id, "name": influx_config.get('bucket_prices')}},
        ]
        permissions = [p for p in permissions if p['resource'].get('name')]

        # Check if a token with this description already exists
        authorizations = auth_api.find_authorizations(org_id=org.id)
        existing_token = None
        if authorizations:
            for auth in authorizations:
                if auth.description == app_token_description:
                    existing_token = auth
                    break

        app_token = None # Initialize app_token
        if existing_token:
            print(f"✅ Application token '{app_token_description}' already exists.")
            print("   To regenerate the token, please delete it from the InfluxDB UI first.")
            # The token value is not available when listing authorizations.
            # We can't retrieve the old token here.
            print("   WARNING: Existing token value cannot be retrieved. You may need to create a new one manually if the old one is lost.")
        else:
            print("Application token not found. Creating it...")
            # --- FIX: Create the authorization request body ---
            authorization_request = Authorization(org_id=org.id, permissions=permissions, description=app_token_description, status="active")
            
            # --- FIX: Call create_authorization with the request body ---
            created_auth = auth_api.create_authorization(authorization=authorization_request)
            
            app_token = created_auth.token
            print(f"✅ Application token created successfully.")

        print("\n--- Initial Setup Complete ---")
        print(f"Organization: {org_name}")
        valid_buckets = [b for b in buckets_to_create if b]
        print(f"Buckets: {', '.join(valid_buckets)}")

        if app_token:
            print("\nIMPORTANT: Your application token and organization are printed below.")
            print("You MUST add these values to your .env file for the application to work correctly.")
            print("-" * 40)
            print(f"INFLUXDB_TOKEN={app_token}")
            print(f"INFLUXDB_ORG={org_name}")
            print("-" * 40)
        
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
