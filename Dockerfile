# Stage 1: Use a specific, slim Python version for consistency and smaller size
FROM python:3.12-slim

# Set environment variables to prevent .pyc file generation and ensure logs appear immediately
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
ENV PYTHONPATH=/app

# Create a non-root user and group first
RUN groupadd -r jules && useradd --no-log-init -r -g jules jules

# Create and set permissions for the app and log directories
RUN mkdir -p /app/logs && chown jules:jules /app/logs

# Set the working directory
WORKDIR /app

# Copy requirements file and install dependencies
# This is done before copying the rest of the code to leverage Docker layer caching
COPY --chown=jules:jules requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the entrypoint script
COPY --chown=jules:jules entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/entrypoint.sh

# Copy the rest of the application code with more granular commands for better caching
COPY --chown=jules:jules jules_bot jules_bot/
COPY --chown=jules:jules tui tui/
COPY --chown=jules:jules scripts scripts/
COPY --chown=jules:jules collectors collectors/
COPY --chown=jules:jules config config/
COPY --chown=jules:jules run.py .
COPY --chown=jules:jules config.ini .
COPY --chown=jules:jules pyproject.toml .

# Switch to the non-root user
USER jules

# Set the entrypoint to our permission-fixing script
ENTRYPOINT ["entrypoint.sh"]
# Set the default command to run the bot
CMD ["python", "jules_bot/main.py"]
