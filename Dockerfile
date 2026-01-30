# Dockerfile for intake web app (Railway deployment)
FROM python:3.11-slim

WORKDIR /app

# Install Python dependencies for intake webapp
RUN pip install --no-cache-dir \
    fastapi==0.115.8 \
    uvicorn==0.30.6 \
    google-api-python-client==2.157.0 \
    google-auth==2.38.0 \
    google-auth-httplib2==0.2.0 \
    google-auth-oauthlib==1.2.1 \
    requests==2.32.3 \
    jinja2==3.1.5 \
    python-multipart==0.0.12

# Copy only intake webapp code (no shared module needed)
COPY intake_webapp/ /app/

# Set port from environment
ENV PORT=8080

# Run the application
CMD uvicorn main:app --host 0.0.0.0 --port $PORT
