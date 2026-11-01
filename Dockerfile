FROM python:3.11-slim

# Set environment variables for Playwright
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install system dependencies for Chromium
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    libglib2.0-0 \
    libnss3 \
    libnspr4 \
    libdbus-1-3 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxcb1 \
    libxkbcommon0 \
    libatspi2.0-0 \
    libx11-6 \
    libxcomposite1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    && rm -rf /var/lib/apt/lists/*

# Copy and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Install Chromium for Playwright
RUN playwright install --with-deps chromium

COPY . .

# Render uses PORT environment variable
EXPOSE 10000

# Increase timeout for long downloads
CMD ["gunicorn", "-w", "1", "-b", "0.0.0.0:10000", "--timeout", "300", "app:app"]
