FROM python:3.12-slim AS base

# Layer 1: system dependencies (cached unless apt changes)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      curl ca-certificates gnupg unzip git \
      libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 \
      libcups2 libdrm2 libdbus-1-3 libxkbcommon0 \
      libxcomposite1 libxdamage1 libxfixes3 libxrandr2 \
      libgbm1 libpango-1.0-0 libcairo2 libasound2 \
      libgtk-3-0 libgdk-pixbuf-2.0-0 libxshmfence1 gnupg2 ffmpeg tzdata \
    && curl -fsSL https://dl.google.com/linux/linux_signing_key.pub | gpg --dearmor -o /usr/share/keyrings/google-chrome.gpg \
    && echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome.gpg] http://dl.google.com/linux/chrome/deb/ stable main" > /etc/apt/sources.list.d/google-chrome.list \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get update \
    && apt-get install -y --no-install-recommends nodejs google-chrome-stable \
    && rm -rf /var/lib/apt/lists/* \
    && curl -fsSL https://deno.land/install.sh | DENO_INSTALL=/usr/local sh

WORKDIR /app

# Layer 2: Python dependencies (cached unless pyproject.toml / uv.lock changes)
COPY pyproject.toml uv.lock README.md ./
RUN mkdir -p telonyx_cinema_bot && touch telonyx_cinema_bot/__init__.py && \
    pip install --no-cache-dir -e . && \
    pip install --no-cache-dir "yt-dlp[default]"

# Layer 3: TikTokAutoUploader v2 (request-based, no Selenium)
RUN git clone https://github.com/makiisthenes/TiktokAutoUploader.git /opt/tiktok-autouploader && \
    cd /opt/tiktok-autouploader && \
    pip install --no-cache-dir -r requirements.txt && \
    cd tiktok_uploader/tiktok-signature && npm install

ENV PYTHONPATH="/opt/tiktok-autouploader"
ENV PLAYWRIGHT_BROWSERS_PATH="0"
ENV PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH="/usr/bin/google-chrome"

# Layer 4: source code (fast, only this busts on code changes)
COPY . .

CMD ["python", "-m", "telonyx_cinema_bot"]
