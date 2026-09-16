# Slim official image — roughly 150MB versus ~1GB for the full one
FROM python:3.12-slim

# Don't write .pyc files; don't buffer stdout so logs appear immediately
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Copy requirements on their own layer first.
# Docker caches layers, so if requirements.txt hasn't changed this pip
# install is reused instead of re-running on every code edit.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Now the application code
COPY app/ ./app/
COPY seed.py .

# Create a non-root user and a data directory it owns.
# Containers run as root by default. If the app is ever compromised,
# root inside the container is a far better starting position for an
# attacker than an unprivileged account.
RUN useradd --create-home appuser \
    && mkdir -p /app/data \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]