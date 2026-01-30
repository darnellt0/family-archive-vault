# Dockerfile for intake web app (Railway deployment)
FROM python:3.11-slim

WORKDIR /app

# Install Python dependencies for intake webapp
# Using Cloudflare R2 (S3-compatible) instead of Google Drive
RUN pip install --no-cache-dir \
    fastapi==0.115.8 \
    uvicorn==0.30.6 \
    boto3==1.35.0 \
    requests==2.32.3 \
    jinja2==3.1.5 \
    python-multipart==0.0.12

# Copy only intake webapp code
COPY intake_webapp/ /app/

# Set port from environment
ENV PORT=8080

# Run the application
CMD uvicorn main:app --host 0.0.0.0 --port $PORT
