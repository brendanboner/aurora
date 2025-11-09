FROM python:3.11-slim

WORKDIR /app

# Copy rabbitmq-client from parent context
COPY rabbitmq-client ./rabbitmq-client

# Copy retriever requirements and install dependencies
COPY retriever/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy retriever application code
COPY retriever/ .

# Default command (can be overridden)
CMD ["python", "main.py"]