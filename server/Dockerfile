FROM python:3.11-slim

WORKDIR /app

# Install system dependencies (antiword for .doc parsing)
RUN apt-get update && apt-get install -y --no-install-recommends antiword && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY server/requirements.txt /app/server/requirements.txt
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt -r server/requirements.txt

# Copy source code
COPY src/ /app/src/
COPY config/ /app/config/
COPY server/ /app/server/

ENV PYTHONPATH=/app
