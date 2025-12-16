# Aurora Curator Dockerfile
# Use Python 3.13 slim image
FROM python:3.13-slim

# Set working directory
WORKDIR /app

# Copy common utilities (auth middleware)
COPY common ./common

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY curator/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download the sentence transformer model to cache it in the docker layer
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/all-mpnet-base-v2')"

# Install local shared libraries (neo4j-client)
COPY neo4j-client ./neo4j-client
RUN pip install --no-cache-dir ./neo4j-client

# Copy curator application code
COPY curator/ .

# Run the curator service directly
CMD ["python", "curator.py"]
