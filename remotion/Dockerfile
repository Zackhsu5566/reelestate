FROM node:20-slim

ENV DEBIAN_FRONTEND=noninteractive

# Chromium for Remotion + CJK fonts for Chinese text rendering
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    chromium \
    fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

ENV REMOTION_CHROME_EXECUTABLE=/usr/bin/chromium

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npx tsc -p tsconfig.server.json
RUN mkdir -p public/jobs out

EXPOSE 3100

CMD ["node", "dist/server/index.js"]
