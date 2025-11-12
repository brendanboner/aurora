# Dockerfile for Load Test Messages Script
FROM python:3.11-slim

WORKDIR /app

# Copy the rabbitmq-client library
COPY rabbitmq-client ./rabbitmq-client

# Copy test messages directory
COPY digester/test_queue .

# Install rabbitmq-client dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Default command (can be overridden)
ENTRYPOINT ["python3", "load_test_messages.py"]
CMD ["--help"]
