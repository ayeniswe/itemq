FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential sqlite3 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app

RUN mkdir -p /data/media
RUN mkdir -p /data/media/inventory
RUN mkdir -p /data/media/barcodes

EXPOSE 8080

ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["python", "server.py", "--host", "0.0.0.0", "--port", "8080"]
