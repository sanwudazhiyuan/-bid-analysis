FROM python:3.11-slim AS base

WORKDIR /app

# Install system dependencies (antiword for .doc parsing)
RUN apt-get update && apt-get install -y --no-install-recommends antiword curl && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd -m -r appuser

# Install Python dependencies
COPY server/requirements.txt /app/server/requirements.txt
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt -r server/requirements.txt

# Copy source code
COPY src/ /app/src/
COPY config/ /app/config/
COPY server/ /app/server/

USER appuser
ENV PYTHONPATH=/app
