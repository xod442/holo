FROM python:3.12-slim

WORKDIR /srv

# Install deps first for better layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY scripts ./scripts

# SQLite lives on a mounted volume so data survives restarts
RUN mkdir -p /data
ENV HOLO_DB_PATH=/data/holo.db

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
