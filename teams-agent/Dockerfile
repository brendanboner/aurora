# syntax=docker/dockerfile:1
# Multi-stage build for Teams Agent
FROM node:20-alpine AS builder

WORKDIR /app

# Copy package files
COPY package*.json ./
COPY tsconfig.json ./

# Install dependencies
RUN --mount=type=cache,target=/root/.npm \
    npm ci

# Copy source code
COPY src ./src

# Build TypeScript
RUN npm run build

# Production stage
FROM node:20-alpine

WORKDIR /app

# Install dumb-init for proper signal handling
RUN apk add --no-cache dumb-init

# Copy package files and install production dependencies only
COPY package*.json ./
RUN npm ci --only=production && \
    npm install --no-save @microsoft/teams-app-test-tool

# Copy built application from builder
COPY --from=builder /app/dist ./dist

# Copy adaptive cards (needed at runtime)
COPY src/adaptiveCards ./dist/adaptiveCards

# Bake in Agents Playground config — points at the bot on localhost:3978
RUN echo '{"botMessagingEndpoint":"http://localhost:3978/api/messages"}' \
    > /app/teamsapptesttool.config.json

# Create non-root user
RUN addgroup -g 1001 -S nodejs && \
    adduser -S nodejs -u 1001 && \
    chown -R nodejs:nodejs /app

USER nodejs

# Expose bot port and Agents Playground port
EXPOSE 3978 56150

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD node -e "require('http').get('http://localhost:3978/api/health', (r) => {process.exit(r.statusCode === 200 ? 0 : 1)})"

# Use dumb-init to handle signals properly
ENTRYPOINT ["dumb-init", "--"]

# Start the bot
CMD ["node", "dist/index.js"]
