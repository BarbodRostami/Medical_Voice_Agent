FROM python:3.10-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main_api.py medical_voice_utils.py ingestion.py ./

# ChromaDB persisted volume mounted at runtime (see docker-compose.yml)
VOLUME ["/app/db"]

EXPOSE 8000

CMD ["python", "main_api.py"]
