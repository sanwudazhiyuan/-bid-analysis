FROM oven/bun:1

WORKDIR /app

# Use Chinese mirror for bun/npm
ENV BUN_INSTALL_NPM_REGISTRY=https://registry.npmmirror.com

# Install dependencies
COPY package.json bun.lock* bunfig.toml ./
RUN bun install --registry=https://registry.npmmirror.com

# Copy source
COPY . .

# Copy .env from example
RUN cp .env.example .env

# Set review timeout to 15 minutes
ENV REVIEW_TIMEOUT_MS=900000

EXPOSE 3000

CMD ["bun", "run", "server.ts"]
