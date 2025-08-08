import os
import sys
from influxdb_client import InfluxDBClient, Bucket, Organization
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
    try:
        # --- 1. Load Configuration ---
        config_manager = ConfigManager()
        influx_config = config_manager.get_section('INFLUXDB')

        url = f"http://{influx_config['host']}:{influx_config['port']}"
        org_name = influx_config['org']

        # Admin token must be provided via environment variable for initial setup
        admin_token = os.getenv("INFLUXDB_ADMIN_TOKEN")
        if not admin_token:
            print("❌ ERROR: INFLUXDB_ADMIN_TOKEN environment variable not set.")
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
            if orgs.orgs:
                org = orgs.orgs[0]
                print(f"✅ Organization '{org_name}' already exists (ID: {org.id}).")
            else:
                print(f"Organization '{org_name}' not found. Creating it...")
                new_org = Organization(name=org_name)
                org = org_api.create_organization(new_org)
                print(f"✅ Organization '{org_name}' created successfully (ID: {org.id}).")
        except ApiException as e:
            if "organization name is already taken" in str(e.body):
                 orgs = org_api.find_organizations(org=org_name)
                 org = orgs.orgs[0]
                 print(f"✅ Organization '{org_name}' already exists (ID: {org.id}).")
            else:
                print(f"❌ ERROR: Could not create or find organization '{org_name}'.")
                print(f"   Reason: {e}")
                sys.exit(1)

        # --- 3. Create Buckets ---
        buckets_to_create = [
            influx_config['bucket_live'],
            influx_config['bucket_testnet'],
            influx_config['bucket_backtest'],
            influx_config['bucket_prices']
        ]

        print("\nChecking for required buckets...")
        for bucket_name in buckets_to_create:
            if not bucket_name:
                print(f"⚠️ WARNING: Bucket name is not defined in config.ini. Skipping.")
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
        app_token_description = "JulesBot Application Token"
        print(f"\nChecking for application token: '{app_token_description}'...")

        # Define permissions for the token
        permissions = [
            # Read access to all buckets
            {"action": "read", "resource": {"type": "buckets", "orgID": org.id}},
            # Write access to the application-specific buckets
            {"action": "write", "resource": {"type": "buckets", "orgID": org.id, "name": influx_config['bucket_live']}},
            {"action": "write", "resource": {"type": "buckets", "orgID": org.id, "name": influx_config['bucket_testnet']}},
            {"action": "write", "resource": {"type": "buckets", "orgID": org.id, "name": influx_config['bucket_backtest']}},
            {"action": "write", "resource": {"type": "buckets", "orgID": org.id, "name": influx_config['bucket_prices']}},
        ]

        # Check if a token with this description already exists
        authorizations = auth_api.find_authorizations(user_id=None, user=None, org_id=org.id)
        existing_token = None
        for auth in authorizations.authorizations:
            if auth.description == app_token_description:
                existing_token = auth
                break

        if existing_token:
            print(f"✅ Application token '{app_token_description}' already exists.")
            print("   To regenerate the token, please delete it from the InfluxDB UI first.")
            app_token = existing_token.token
        else:
            print("Application token not found. Creating it...")
            created_auth = auth_api.create_authorization(org_id=org.id, permissions=permissions)
            created_auth.description = app_token_description # Description must be set after creation
            auth_api.update_authorization(created_auth.id, created_auth)
            app_token = created_auth.token
            print(f"✅ Application token created successfully.")

        print("\n--- Initial Setup Complete ---")
        print(f"Organization: {org_name}")
        print(f"Buckets: {', '.join(buckets_to_create)}")
        print("\nIMPORTANT: Your application token is printed below.")
        print("You MUST add this token to your .env file as INFLUXDB_TOKEN.")
        print("-" * 30)
        print(f"INFLUXDB_TOKEN={app_token}")
        print("-" * 30)
        print("\nSetup script finished.")

    except FileNotFoundError as e:
        print(f"❌ ERROR: Configuration file not found at '{e.filename}'.")
        print("   Please ensure config.ini exists in the root directory.")
        sys.exit(1)
    except Exception as e:
        print(f"❌ An unexpected error occurred: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        if 'client' in locals() and client:
            client.close()

if __name__ == "__main__":
    main()
