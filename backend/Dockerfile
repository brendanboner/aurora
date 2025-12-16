FROM python:3.12-slim

WORKDIR /app

# Copy common utilities (auth middleware)
COPY common ./common

# Copy local client libraries and install
COPY neo4j-client ./neo4j-client
RUN pip install --no-cache-dir --upgrade pip && \
	pip install --no-cache-dir ./neo4j-client

# Copy backend and install as editable package
COPY backend ./backend
WORKDIR /app/backend
RUN pip install --no-cache-dir -e .

# Switch back to /app so common module is in Python path
WORKDIR /app

EXPOSE 8000
CMD ["uvicorn", "backend.src.api:app", "--host", "0.0.0.0", "--port", "8000"]
