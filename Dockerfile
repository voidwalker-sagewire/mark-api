FROM python:3.10-slim

# Install system dependencies including ffmpeg for video processing
RUN apt-get update && apt-get install -y \
    ffmpeg \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Upgrade pip, setuptools, and wheel FIRST to fix pkg_resources issue
RUN pip install --no-cache-dir --upgrade pip setuptools wheel

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 5009

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "5009"]
