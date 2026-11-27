FROM node:20-alpine AS builder

# Install system dependencies
RUN apk add --no-cache \
    python3 \
    py3-pip \
    ffmpeg \
    && pip3 install --break-system-packages yt-dlp

# Set working directory
WORKDIR /app

# Copy package files and workspace config (with allowBuilds for sharp)
COPY package*.json pnpm-lock.yaml* pnpm-workspace.yaml* ./

# Install dependencies
RUN npm install -g pnpm && (pnpm approve-builds --all || true) && pnpm install

# Copy source code
COPY . .

# Build the application
RUN pnpm build

# Production stage
FROM node:20-alpine AS runner

# Install system dependencies
RUN apk add --no-cache \
    python3 \
    py3-pip \
    ffmpeg \
    && pip3 install --break-system-packages yt-dlp

WORKDIR /app

ENV NODE_ENV=production
ENV PORT=3000
ENV HOSTNAME="0.0.0.0"

# Copy built application
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/public ./public
COPY --from=builder /app/package*.json ./
COPY --from=builder /app/pnpm-lock.yaml* ./
COPY --from=builder /app/pnpm-workspace.yaml* ./

# Install only production dependencies
RUN npm install -g pnpm && (pnpm approve-builds --all || true) && pnpm install --prod

# Expose port
EXPOSE 3000

# Start the application
CMD ["pnpm", "start"]
