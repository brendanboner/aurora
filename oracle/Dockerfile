# syntax=docker/dockerfile:1
FROM python:3.12-slim

WORKDIR /app

# Copy common utilities (auth middleware, telemetry)
COPY common ./common

# Copy local client libraries and install
COPY neo4j-client ./neo4j-client
COPY rabbitmq-client ./rabbitmq-client
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --upgrade pip && \
    pip install ./neo4j-client ./rabbitmq-client

# Copy oracle service and install as editable package
COPY oracle ./oracle
WORKDIR /app/oracle
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -e .

# Switch back to /app so common module is in Python path
WORKDIR /app

EXPOSE 8000
CMD ["uvicorn", "oracle.src.api:app", "--host", "0.0.0.0", "--port", "8000"]
