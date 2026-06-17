FROM python:3.12-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      curl ca-certificates gnupg unzip \
      libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 \
      libcups2 libdrm2 libdbus-1-3 libxkbcommon0 \
      libxcomposite1 libxdamage1 libxfixes3 libxrandr2 \
      libgbm1 libpango-1.0-0 libcairo2 libasound2 \
      libgtk-3-0 libgdk-pixbuf-2.0-0 libxshmfence1 \
      ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Node.js for tiktokautouploader
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && \
    apt-get install -y --no-install-recommends nodejs && \
    rm -rf /var/lib/apt/lists/*

# Deno for yt-dlp EJS (JavaScript challenge solver)
RUN curl -fsSL https://deno.land/install.sh | DENO_INSTALL=/usr/local sh

WORKDIR /app
COPY . .

# yt-dlp[default] includes EJS scripts for YouTube JS challenge solving
RUN pip install --no-cache-dir -e . && pip install --no-cache-dir "yt-dlp[default]"

RUN phantomwright_driver install chromium

CMD ["python", "-m", "telonyx_cinema_bot"]
