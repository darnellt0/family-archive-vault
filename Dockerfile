# Dockerfile for intake web app
FROM python:3.10-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt .

# Install Python dependencies (intake-only subset)
RUN pip install --no-cache-dir \
    fastapi==0.109.0 \
    uvicorn[standard]==0.27.0 \
    python-multipart==0.0.6 \
    aiofiles==23.2.1 \
    pydantic==2.5.3 \
    pydantic-settings==2.1.0 \
    google-auth==2.27.0 \
    google-auth-oauthlib==1.2.0 \
    google-auth-httplib2==0.2.0 \
    google-api-python-client==2.116.0 \
    python-dotenv==1.0.1 \
    loguru==0.7.2

# Copy application code
COPY shared/ /app/shared/
COPY intake_webapp/ /app/intake_webapp/

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:8000/api/health')"

# Run the application
CMD ["uvicorn", "intake_webapp.main:app", "--host", "0.0.0.0", "--port", "8000"]
