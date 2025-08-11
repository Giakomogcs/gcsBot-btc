import os
import sys
import importlib.util
from pathlib import Path

def run_migrations():
    """
    Dynamically finds and runs all migration scripts in the 'migrations' subdirectory.
    """
    migrations_path = Path(__file__).parent / 'migrations'

    if not migrations_path.is_dir():
        print(f"❌ ERROR: Migrations directory not found at '{migrations_path}'")
        sys.exit(1)

    # Get all python files, sort them to ensure execution order
    migration_files = sorted(migrations_path.glob('[0-9][0-9][0-9]_*.py'))

    if not migration_files:
        print("No migration scripts found to execute.")
        return

    print(f"Found {len(migration_files)} migration script(s).")
    print("-" * 30)

    for script_path in migration_files:
        print(f"▶️  Running migration: {script_path.name}")

        try:
            # Dynamically load the module from its file path
            spec = importlib.util.spec_from_file_location(script_path.stem, script_path)
            if spec and spec.loader:
                migration_module = importlib.util.module_from_spec(spec)
                sys.modules[script_path.stem] = migration_module
                spec.loader.exec_module(migration_module)

                # Check if the module has a 'main' function and run it
                if hasattr(migration_module, 'main'):
                    migration_module.main()
                    print(f"✅ Finished migration: {script_path.name}")
                else:
                    print(f"⚠️  WARNING: No 'main' function found in {script_path.name}. Skipping.")
            else:
                print(f"❌ ERROR: Could not load module from {script_path.name}")

        except Exception as e:
            print(f"❌ ERROR: An error occurred while running {script_path.name}.")
            print(f"   Reason: {e}")
            # Optional: Decide if you want to stop on the first error
            # sys.exit(1)

        print("-" * 30)

    print("All migrations have been processed.")

if __name__ == "__main__":
    run_migrations()
