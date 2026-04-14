FROM python:3.11-slim AS base

WORKDIR /app

# Use Chinese mirror for apt
RUN sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || \
    sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list 2>/dev/null || true

# Install system dependencies (antiword for .doc parsing, LibreOffice for .doc conversion)
RUN apt-get update && apt-get install -y --no-install-recommends \
    antiword \
    libreoffice-writer \
    fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user and data directory
RUN useradd -m -r appuser && mkdir -p /data/uploads /data/generated /data/reviews && chown -R appuser:appuser /data

# Install Python dependencies
COPY server/requirements.txt /app/server/requirements.txt
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --timeout=120 -i https://mirrors.aliyun.com/pypi/simple/ -r requirements.txt -r server/requirements.txt

# Copy source code
COPY src/ /app/src/
COPY config/ /app/config/
COPY server/ /app/server/

USER appuser
ENV PYTHONPATH=/app
