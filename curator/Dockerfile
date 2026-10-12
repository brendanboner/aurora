# syntax=docker/dockerfile:1
# ============================================
# BUILD STAGE - Compile dependencies with gcc
# ============================================
FROM python:3.13-slim AS builder

WORKDIR /build

# Install build-time dependencies (gcc needed for scipy, scikit-learn, numpy)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    gfortran \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies to a temporary location
COPY curator/requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --prefix=/install -r requirements.txt

# Install local shared library (neo4j-client)
COPY neo4j-client ./neo4j-client
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --prefix=/install ./neo4j-client


# ============================================
# RUNTIME STAGE - Clean image without gcc
# ============================================
FROM python:3.13-slim

WORKDIR /app

# Copy only the installed packages from builder stage (no gcc/g++/gfortran!)
COPY --from=builder /install /usr/local

# Copy common utilities (auth middleware)
COPY common ./common

# Copy curator application code (excludes testing/ via .dockerignore)
COPY curator/ .

# Expose port
EXPOSE 8000

# Run the curator service directly
CMD ["python", "curator.py"]
