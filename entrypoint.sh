#!/bin/sh
#
# This script ensures that the user running the container has ownership of
# the logs directory, which is necessary when using Docker volumes on
# some systems (like Windows with WSL2).

echo "Entrypoint: Ensuring log directory permissions..."
chown -R jules:jules /app/logs
echo "Entrypoint: Permissions updated."

# Execute the main command passed to the container
exec "$@"
