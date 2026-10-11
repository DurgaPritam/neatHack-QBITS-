FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app app
COPY fixtures fixtures

# uid 1000 = the ubuntu user on the host, so the bind-mounted backups dir is writable
RUN useradd --uid 1000 --create-home app && mkdir -p /data /backups && chown app:app /data /backups
USER app

EXPOSE 8000
# One worker: the audit queues live in this process. --proxy-headers: real client IPs from
# Caddy (only Caddy can reach this port) for the per-IP limits.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips", "*", "--no-server-header"]
