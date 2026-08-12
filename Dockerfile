FROM python:3.12-slim

WORKDIR /srv

# Install deps first for better layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY scripts ./scripts

# Run as a non-root user. /data is the SQLite volume mount; owning it in the image
# means a freshly-created named volume inherits this ownership.
RUN useradd -r -u 10001 holo \
    && mkdir -p /data \
    && chown -R holo:holo /data /srv
ENV HOLO_DB_PATH=/data/holo.db

USER holo

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
