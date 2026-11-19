FROM python:3.12-slim

WORKDIR /srv

# No .pyc files, and logs appear immediately in `docker compose logs`.
# MPLCONFIGDIR: matplotlib needs a writable folder for its cache, even as a non-root user.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MPLCONFIGDIR=/tmp/matplotlib

# Install dependencies first so Docker caches this layer until requirements.txt changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# Run as a normal user, not root.
RUN useradd --create-home --uid 1001 saathi
USER saathi

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

# One worker keeps memory low on a small VPS and keeps database connections within Supabase's limits.
# Endpoints are sync (def), so FastAPI already runs them concurrently in a thread pool.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
