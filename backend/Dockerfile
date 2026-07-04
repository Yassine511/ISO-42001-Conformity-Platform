# Base image pinned by digest for reproducible builds. Refresh periodically
# (docker pull python:3.12-slim, then update the digest) to pick up OS security
# fixes — a pinned digest does not receive them automatically.
FROM python:3.12-slim@sha256:423ed6ab25b1921a477529254bfeeabf5855151dc2c3141699a1bfc852199fbf

WORKDIR /app

# Pinned constraints make the image resolve the SAME dependency versions the
# test suite ran against — requirements.txt alone uses open ranges, so a later
# build silently drifts (observed: uvicorn/numpy). Regenerate constraints.txt
# from the tested venv (pip freeze) when dependencies change intentionally.
COPY requirements.txt constraints.txt ./
# Pin pip too so the resolver itself is reproducible (bump deliberately).
RUN pip install --no-cache-dir --upgrade "pip==25.0.1" \
    && pip install --no-cache-dir -r requirements.txt -c constraints.txt

COPY app ./app
COPY alembic.ini .
COPY alembic ./alembic

# Run unprivileged. Pre-create the embedding-model cache dir owned by that user
# so a fresh named volume inherits the ownership (Docker seeds an empty volume
# from the image path) and fastembed can write the downloaded model.
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /models/fastembed \
    && chown -R appuser:appuser /app /models
USER appuser

EXPOSE 8000
# Dependency-aware /api/health returns 503 when Postgres/Qdrant are down, so the
# container is reported unhealthy instead of merely "running".
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health').read()"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
