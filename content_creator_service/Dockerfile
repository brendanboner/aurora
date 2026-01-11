FROM python:3.12-slim

WORKDIR /app

# Copy common utilities (auth middleware, telemetry)
COPY common ./common

# Copy local client libraries and install
COPY neo4j-client ./neo4j-client
COPY rabbitmq-client ./rabbitmq-client
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir ./neo4j-client \
    && pip install --no-cache-dir ./rabbitmq-client

# Copy content_creator_service and install as editable package
COPY content_creator_service ./content_creator_service
WORKDIR /app/content_creator_service
RUN pip install --no-cache-dir -e .

# Switch back to /app so common module is in Python path
WORKDIR /app

EXPOSE 8000
CMD ["uvicorn", "content_creator_service.src.api:app", "--host", "0.0.0.0", "--port", "8000"]
