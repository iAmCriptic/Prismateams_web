# ==========================================
# Prismateams – Multi-Stage Produktions-Image
# ==========================================

# ------------------------------------------
# Stage 1: Build-Umgebung
# ------------------------------------------
FROM python:3.12-slim-bookworm AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

# Build-Tools nur temporär in Stage 1 installieren (kein libmariadb-dev nötig, da PyMySQL pure Python ist)
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libffi-dev \
        libjpeg62-turbo-dev \
        libssl-dev \
        pkg-config \
        zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# Venv vorbereiten und Pakete installieren
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip setuptools wheel \
    && /opt/venv/bin/pip install --no-cache-dir -r requirements.txt

# ------------------------------------------
# Stage 2: Minimales Runtime-Image
# ------------------------------------------
FROM python:3.12-slim-bookworm AS runner

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FLASK_ENV=production \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# Basis-OS absichern & updaten, ausschließlich Laufzeit-Tools installieren
RUN apt-get update && apt-get upgrade -y && apt-get install -y --no-install-recommends \
        curl \
        ffmpeg \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Venv aus Stage 1 übernehmen (enthält alle fertig installierten Python-Module)
COPY --from=builder /opt/venv /opt/venv

# Anwendungsquellcode kopieren
COPY . .

# Vendor-Assets die nicht im Git liegen (Excalidraw UMD o. ä.)
RUN python scripts/download_excalidraw_vendor.py 2>/dev/null || true \
    && python scripts/download_youtubei_vendor.py 2>/dev/null || true

RUN mkdir -p uploads instance \
    && chmod +x docker/entrypoint.sh

# Non-root User
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
