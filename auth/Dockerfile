# syntax=docker/dockerfile:1
FROM python:3.11-slim

WORKDIR /app

# Copy common utilities (telemetry)
COPY common ./common

# Install dependencies
COPY auth/requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt

# Copy application code
COPY auth/auth.py auth/settings.py ./
COPY auth/services/ ./services/
COPY auth/utils/ ./utils/

# Expose port
EXPOSE 8000

# Run the application
CMD ["uvicorn", "auth:app", "--host", "0.0.0.0", "--port", "8000"]
