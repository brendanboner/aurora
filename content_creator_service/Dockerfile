FROM python:3.12-slim

WORKDIR /app

# Install shared local libraries first for caching
COPY neo4j-client ./neo4j-client
COPY rabbitmq-client ./rabbitmq-client
COPY common ./common
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir ./neo4j-client \
    && pip install --no-cache-dir ./rabbitmq-client

# Install service in editable mode for dev convenience
COPY content_creator_service ./content_creator_service
WORKDIR /app/content_creator_service
RUN pip install --no-cache-dir -e .

EXPOSE 8003
CMD ["uvicorn", "src.api:app", "--host", "0.0.0.0", "--port", "8003"]
