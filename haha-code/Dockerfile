FROM oven/bun:1

WORKDIR /app

# Use Chinese mirror for bun/npm
ENV BUN_INSTALL_NPM_REGISTRY=https://registry.npmmirror.com

# Install dependencies
COPY package.json bun.lock* bunfig.toml ./
RUN bun install --registry=https://registry.npmmirror.com

# Copy source
COPY . .

# .env is NOT created at build time — docker-compose env vars are the primary
# source. The /config endpoint's writeConfigToEnv() will create .env at runtime
# when admin saves config.

# Set review timeout to 15 minutes
ENV REVIEW_TIMEOUT_MS=900000

EXPOSE 3000

CMD ["bun", "run", "server.ts"]
