# syntax=docker/dockerfile:1
# Neo4j Init Container
# One-time initialization for schema and base data

FROM python:3.12-slim

WORKDIR /app

# Install the neo4j-client package (includes openai for embeddings by default)
# Note: pyproject.toml includes package-data config to bundle initial_data.json
COPY neo4j-client/ /app/neo4j-client/
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install /app/neo4j-client/

# Copy init script
COPY neo4j-init/init.py /app/init.py

# Run initialization
CMD ["python", "init.py"]
