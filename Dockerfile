# Stage 1: Use a specific, slim Python version for consistency and smaller size
FROM python:3.12-slim

# Set the working directory inside the container
WORKDIR /app

# Set environment variables to prevent .pyc file generation and ensure logs appear immediately
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
ENV PYTHONPATH=/app

# --- THE CACHING TRICK ---
# First, copy ONLY the requirements file. Docker caches this layer.
COPY requirements.txt .

# Second, install the dependencies. This step uses the cache from above.
RUN pip install --no-cache-dir -r requirements.txt

# Third, now that dependencies are cached, copy the rest of your application code.
COPY . .

# Create a non-root user for security and create log directory
RUN groupadd -r jules && useradd --no-log-init -r -g jules jules
RUN mkdir -p /app/logs && chown -R jules:jules /app

# Switch to the non-root user
USER jules

# The command to run your application when the container starts
CMD ["python", "jules_bot/main.py"]
