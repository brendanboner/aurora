# Use Python 3.13 slim image
FROM python:3.13-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy shared libraries first (for better caching)
COPY rabbitmq-client ./rabbitmq-client
COPY neo4j-client ./neo4j-client

# Copy digester application code
COPY digester/ .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Run the application
CMD ["python", "main.py"]
