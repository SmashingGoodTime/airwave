# Stage 1: Build frontend
FROM node:22-slim AS frontend-build
WORKDIR /app/frontend
# Copy manifests first so the npm ci layer is cached across source changes
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ .
RUN npm run build

# Stage 2: Python application
FROM python:3.11-slim
WORKDIR /app

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy database migrations and application code
COPY alembic.ini .
COPY migrations/ migrations/
COPY server/ server/

# Copy frontend build from stage 1
COPY --from=frontend-build /app/frontend/dist frontend/dist

# Run as non-root. UID 1000 matches the default first user on most Linux
# hosts so the bind-mounted ./audio directory stays writable. /data holds
# the SQLite database on the named "radio-data" volume, which inherits this
# mountpoint's ownership (see docker-compose.yml); /app/audio is the
# generated-audio volume; /app itself must be writable for the
# wizard-managed .env file.
RUN useradd --uid 1000 --user-group --no-create-home radio && \
    mkdir -p /data /app/audio && \
    chown -R radio:radio /data /app

USER radio

EXPOSE 8000

# curl is not installed in python:slim, so probe with the stdlib instead.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/setup/status', timeout=4)"]

CMD ["uvicorn", "server.main:app", "--host", "0.0.0.0", "--port", "8000"]
