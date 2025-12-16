FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY auth/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY auth/auth.py auth/settings.py ./
COPY auth/services/ ./services/
COPY auth/utils/ ./utils/

# Expose port
EXPOSE 8000

# Run the application
CMD ["uvicorn", "auth:app", "--host", "0.0.0.0", "--port", "8000"]
