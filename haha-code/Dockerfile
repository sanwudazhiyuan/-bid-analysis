FROM oven/bun:1

# Install curl for healthcheck and git (required by haha-code)
RUN sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || \
    sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list 2>/dev/null || true && \
    apt-get update && apt-get install -y --no-install-recommends curl git && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install dependencies
COPY package.json bunfig.toml ./
RUN bun install

# Copy source
COPY . .

# Copy .env from example
RUN cp .env.example .env

# Set review timeout to 15 minutes
ENV REVIEW_TIMEOUT_MS=900000

EXPOSE 3000

CMD ["bun", "run", "server.ts"]
