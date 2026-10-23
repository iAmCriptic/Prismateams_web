# Prismateams – Produktions-Image (Gunicorn + Flask)
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FLASK_ENV=production \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        ffmpeg \
        libffi-dev \
        libjpeg62-turbo-dev \
        libmariadb-dev \
        libssl-dev \
        pkg-config \
        zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip install -r requirements.txt

COPY . .

# Vendor-Assets die nicht im Git liegen (Excalidraw UMD o. ä.)
RUN python scripts/download_excalidraw_vendor.py 2>/dev/null || true \
    && python scripts/download_youtubei_vendor.py 2>/dev/null || true

RUN mkdir -p uploads instance \
    && chmod +x docker/entrypoint.sh

# Non-root
RUN useradd --create-home --uid 1000 --shell /bin/bash appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=5 \
    CMD curl -sf http://127.0.0.1:5000/ || exit 1

ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["gunicorn", \
     "--worker-class", "gthread", \
     "--workers", "2", \
     "--threads", "8", \
     "--bind", "0.0.0.0:5000", \
     "--timeout", "180", \
     "--graceful-timeout", "30", \
     "--max-requests", "1000", \
     "--max-requests-jitter", "100", \
     "--access-logfile", "-", \
     "--error-logfile", "-", \
     "wsgi:app"]
