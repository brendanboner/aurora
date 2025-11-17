# Use Python 3.13 slim image
FROM python:3.13-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY digester/requirements.txt . 
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download the sentence transformer model to cache it in the docker layer
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/all-mpnet-base-v2')"

# Install local shared libraries outside of requirements.txt so docker can cache the other requirements
# These get updated during development and will need to be rebuilt more often
# Once no longer in development, move the copy up and add the requirements into the .txt 
COPY rabbitmq-client ./rabbitmq-client
COPY neo4j-client ./neo4j-client

RUN pip install -e rabbitmq-client
RUN pip install -e neo4j-client

# Copy digester application code
COPY digester/ .

# Run the application
CMD ["python", "main.py"]
