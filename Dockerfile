# syntax=docker/dockerfile:1
# SilverFile - local classroom prototype.  Build and start:  docker compose up --build
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    SILVERFILE_VAR_DIR=/data

WORKDIR /app
COPY requirements.lock requirements.txt ./
# The lock file is the complete, tested dependency set (it uses opencv-python-headless, so no
# system packages are needed). An optional "ca_bundle" build secret lets builds behind a
# TLS-inspecting proxy trust it; normal builds do not need it.
RUN --mount=type=secret,id=ca_bundle,required=false \
    if [ -f /run/secrets/ca_bundle ]; then export PIP_CERT=/run/secrets/ca_bundle; fi; \
    pip install --no-deps -r requirements.lock

COPY . .
RUN useradd --create-home --uid 1000 silverfile \
    && mkdir -p /data \
    && chown -R silverfile:silverfile /data /app
USER silverfile

EXPOSE 8501
VOLUME ["/data"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8501/_stcore/health').status == 200 else 1)"
CMD ["python", "run.py", "ui", "--port", "8501", "--address", "0.0.0.0"]
