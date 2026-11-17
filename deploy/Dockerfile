FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    TZ=America/Argentina/Buenos_Aires

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg fonts-inter fonts-gfs-baskerville ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README* ./
COPY src ./src
COPY scripts ./scripts
RUN python -m pip install --upgrade pip \
    && python -m pip install . google-auth-oauthlib google-api-python-client playwright \
    && playwright install --with-deps chromium \
    && useradd --create-home --uid 10001 canal \
    && mkdir -p /app/data /var/log/canal \
    && chown -R canal:canal /app /var/log/canal /ms-playwright

USER canal
VOLUME ["/app/data"]
CMD ["sleep", "infinity"]
