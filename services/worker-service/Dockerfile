FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# No EXPOSE — this container runs a Celery worker, not an HTTP server. The command that
# actually starts it lives in infra/docker-compose.yml.
