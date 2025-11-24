FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY tests/requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the entire neo4j-client package (from parent directory)
COPY . .

# Install the package in development mode
RUN pip install -e .

# Set Python path
ENV PYTHONPATH=/app:$PYTHONPATH

# Set working directory to tests
WORKDIR /app/tests

# Default command shows help
CMD ["bash", "-c", "cd /app && make help"]
