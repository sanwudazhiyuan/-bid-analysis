FROM python:3.11-slim AS base

WORKDIR /app

# Use Tsinghua mirror for apt (Debian Trixie)
RUN mkdir -p /etc/apt/sources.list.d && \
    rm -f /etc/apt/sources.list.d/debian.sources /etc/apt/sources.list && \
    echo "Types: deb" > /etc/apt/sources.list.d/debian.sources && \
    echo "URIs: https://mirrors.tuna.tsinghua.edu.cn/debian/" >> /etc/apt/sources.list.d/debian.sources && \
    echo "Suites: trixie trixie-updates" >> /etc/apt/sources.list.d/debian.sources && \
    echo "Components: main contrib" >> /etc/apt/sources.list.d/debian.sources && \
    echo "Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg" >> /etc/apt/sources.list.d/debian.sources && \
    echo "" >> /etc/apt/sources.list.d/debian.sources && \
    echo "Types: deb" >> /etc/apt/sources.list.d/debian.sources && \
    echo "URIs: https://mirrors.tuna.tsinghua.edu.cn/debian-security/" >> /etc/apt/sources.list.d/debian.sources && \
    echo "Suites: trixie-security" >> /etc/apt/sources.list.d/debian.sources && \
    echo "Components: main contrib" >> /etc/apt/sources.list.d/debian.sources && \
    echo "Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg" >> /etc/apt/sources.list.d/debian.sources

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
