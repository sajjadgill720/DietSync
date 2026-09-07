# DietSync Backend & Worker Dockerfile
FROM python:3.11-slim

# Prevent Python from writing .pyc files and enable unbuffered logging
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY . .

# Ensure scripts have unix line endings and execution permissions
RUN sed -i 's/\r$//' /app/start.sh && chmod +x /app/start.sh

# Default port
EXPOSE 8000

# Start both FastAPI and LangGraph Worker in one container
CMD ["/bin/sh", "/app/start.sh"]
