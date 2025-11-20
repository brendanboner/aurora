FROM python:3.12-slim

WORKDIR /app

# Copy local client libraries and install
COPY neo4j-client ./neo4j-client
RUN pip install --no-cache-dir --upgrade pip && \
	pip install --no-cache-dir ./neo4j-client

# Copy backend and install as editable package
COPY backend ./backend
WORKDIR /app/backend
RUN pip install --no-cache-dir -e .

EXPOSE 8000
CMD ["uvicorn", "src.api:app", "--host", "0.0.0.0", "--port", "8000"]
