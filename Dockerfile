# Production Dockerfile for DocuMind AI
FROM python:3.11-slim

# Install system dependencies including Tesseract OCR and MySQL client libraries
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    tesseract-ocr \
    tesseract-ocr-eng \
    default-libmysqlclient-dev \
    pkg-config \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy dependency specifications
COPY requirements.txt .

# Install Python packages
RUN pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir waitress

# Copy application source code
COPY . .

# Set environment defaults
ENV PYTHONUNBUFFERED=1 \
    TF_ENABLE_ONEDNN_OPTS=0 \
    USE_TF=0 \
    USE_TORCH=1 \
    PORT=5000 \
    HOST=0.0.0.0

EXPOSE 5000

# Health check endpoint
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:5000/favicon.ico || exit 1

# Launch using production WSGI
CMD ["python", "wsgi.py"]
