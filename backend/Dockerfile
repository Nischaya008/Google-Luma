# Use python 3.11 slim as the base image
FROM python:3.11-slim

# Hugging Face requires a non-root user with UID 1000 for strict security
RUN useradd -m -u 1000 user

# Set working directory
WORKDIR /app

# Prevent Python from writing pyc files and enable unbuffered logging
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install system dependencies (including geo-packages for GeoPandas)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gdal-bin \
    libgdal-dev \
    libspatialindex-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements files first to leverage Docker layer caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Create cache directories for graphs, VIIRS, crime, huggingface, and upstash limits,
# and ensure the non-root user completely owns them for write access
RUN mkdir -p /app/data/graph /app/data/viirs /app/data/crime \
    && chown -R user:user /app

# Switch to the non-root user
USER user

# Start the FastAPI application with Uvicorn.
# HF Spaces mandates Port 7860.
# We utilize 16GB RAM and 2 vCPUs explicitly by spawning 2 workers.
CMD ["sh", "-c", "\
  if [ -n \"$GEE_KEY_BASE64\" ]; then \
    echo \"$GEE_KEY_BASE64\" | base64 -d > /app/gee_key.json && \
    export GEE_SERVICE_ACCOUNT_KEY=/app/gee_key.json; \
  fi && \
  uvicorn main:app --host 0.0.0.0 --port 7860 --workers 2\
"]
