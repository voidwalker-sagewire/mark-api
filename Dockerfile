FROM python:3.10-slim

# Install minimal system dependencies without extra GUI bloat
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN pip install --no-cache-dir --upgrade pip setuptools wheel

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 5009

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "5009"]
