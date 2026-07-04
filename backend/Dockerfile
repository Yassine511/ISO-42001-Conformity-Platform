FROM python:3.12-slim

WORKDIR /app

# Pinned constraints make the image resolve the SAME dependency versions the
# test suite ran against — requirements.txt alone uses open ranges, so a later
# build silently drifts (observed: uvicorn/numpy). Regenerate constraints.txt
# from the tested venv (pip freeze) when dependencies change intentionally.
COPY requirements.txt constraints.txt ./
RUN pip install --no-cache-dir -r requirements.txt -c constraints.txt

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
