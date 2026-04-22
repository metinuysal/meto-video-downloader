FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --upgrade pip setuptools wheel \
    && pip install --no-cache-dir -r /app/requirements.txt

COPY . /app

RUN useradd -m -u 10001 appuser \
    && mkdir -p /data \
    && chown -R appuser:appuser /app /data
USER appuser

ENV BULK_VIDEO_HOST=0.0.0.0
ENV BULK_VIDEO_PORT=5000
ENV BULK_VIDEO_DEBUG=0
ENV BULK_VIDEO_DB_PATH=/data/bulk_video.db
ENV BULK_VIDEO_VIDEO_DIR=/data/videos

EXPOSE 5000

ENTRYPOINT ["sh", "/app/docker-entrypoint.sh"]
CMD ["python", "app.py"]
