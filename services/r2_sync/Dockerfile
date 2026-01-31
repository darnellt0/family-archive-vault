FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install dependencies
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy the sync worker code
COPY . /app/services/r2_sync/

# Create empty __init__.py for services package
RUN mkdir -p /app/services && touch /app/services/__init__.py

# Create data and config directories
RUN mkdir -p /app/data /app/cache /app/config

ENV FAMILY_ARCHIVE_ROOT=/app

CMD ["python", "-m", "services.r2_sync"]
