FROM python:3.10-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./backend/
# ChromaDB persisted volume mounted at runtime (see docker-compose.yml)
VOLUME ["/app/db"]

ENV PYTHONPATH=/app

EXPOSE 8000

CMD ["uvicorn", "backend.main_api:app", "--host", "0.0.0.0", "--port", "8000"]
