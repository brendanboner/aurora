FROM python:3.11-slim

WORKDIR /app

# Copy common utilities (auth middleware)
COPY common ./common

# Copy rabbitmq-client from parent context
COPY rabbitmq-client ./rabbitmq-client
COPY neo4j-client ./neo4j-client

# Copy retriever requirements and install dependencies
COPY retriever/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy retriever application code
COPY retriever/ .

# Expose port
EXPOSE 8000

# Run the new retriever service with uvicorn
CMD ["uvicorn", "retriever:app", "--host", "0.0.0.0", "--port", "8000"]