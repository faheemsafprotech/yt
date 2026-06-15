# Use the official Python slim base image
FROM python:3.10-slim

# Install system dependencies (ffmpeg and Node.js for signature decryption)
RUN apt-get update && apt-get install -y \
    ffmpeg \
    curl \
    gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Set working directory in container
WORKDIR /app

# Copy dependency definition and install packages
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code and frontend static assets
COPY . .

# Create the downloads directory
RUN mkdir -p downloads

# Expose the port Gunicorn will bind to
EXPOSE 5000

# Start the application using gunicorn WSGI production server
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--threads", "4", "--timeout", "300", "app:app"]
