# ============================================
# BUILD STAGE - Compile dependencies with gcc
# ============================================
FROM python:3.13-slim AS builder

WORKDIR /build

# Install build-time dependencies (gcc needed for some packages)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies to a temporary location
COPY digester/requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# Install local shared libraries
COPY common ./common
COPY rabbitmq-client ./rabbitmq-client
COPY neo4j-client ./neo4j-client
RUN pip install --no-cache-dir --prefix=/install ./rabbitmq-client
RUN pip install --no-cache-dir --prefix=/install ./neo4j-client


# ============================================
# RUNTIME STAGE - Clean image without gcc
# ============================================
FROM python:3.13-slim

WORKDIR /app

# Copy only the installed packages from builder stage (no gcc!)
COPY --from=builder /install /usr/local

# Copy digester application code (excludes testing/ via .dockerignore)
COPY digester/ .

# Copy shared common module
COPY common ./common

# Run the application
CMD ["python", "digester.py"]
