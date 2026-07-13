#!/bin/bash
# Run on company server after .env is in place.
# Usage: bash scripts/server_setup.sh
set -euo pipefail

PROJECT_DIR="${1:-$HOME/Medical_Voice_Agent}"
cd "$PROJECT_DIR"

echo "=== Checking .env (Parmin) ==="
required=(LIARA_ENDPOINT LIARA_BUCKET LIARA_ACCESS_KEY LIARA_SECRET_KEY)
for key in "${required[@]}"; do
  if ! grep -q "^${key}=" .env 2>/dev/null; then
    echo "ERROR: missing ${key} in .env"
    exit 1
  fi
done
if ! grep -q "^PUBLIC_API_URL=" .env 2>/dev/null; then
  echo "PUBLIC_API_URL=http://192.168.1.15:8000" >> .env
  echo "Added PUBLIC_API_URL to .env"
fi
# Reject obvious wrong credentials (GitHub token prefix)
if grep -q "LIARA_ACCESS_KEY=ghp_" .env 2>/dev/null; then
  echo "ERROR: LIARA_ACCESS_KEY looks like a GitHub token — use Parmin Cloud keys"
  exit 1
fi

echo "=== Git pull ==="
git fetch origin
git checkout feature/async-stt-jobs 2>/dev/null || true
git pull origin feature/async-stt-jobs 2>/dev/null || git pull origin HEAD

echo "=== Ollama host (Linux server) ==="
if grep -q 'OLLAMA_HOST=http://host.docker.internal:11434' docker-compose.yml 2>/dev/null; then
  sed -i.bak 's|OLLAMA_HOST=http://host.docker.internal:11434|OLLAMA_HOST=http://172.17.0.1:11434|' docker-compose.yml
  echo "Set OLLAMA_HOST to 172.17.0.1 for Linux"
fi

echo "=== Docker rebuild backend ==="
sudo docker compose up -d --build backend

echo "=== Health check ==="
sleep 8
curl -sf http://localhost:8000/ | head -c 200
echo ""

echo "=== S3 upload smoke test ==="
sudo docker compose exec -T backend python - <<'PY'
import os, boto3
from botocore.config import Config as C
from dotenv import load_dotenv
load_dotenv()
s3 = boto3.client(
    "s3",
    endpoint_url=os.getenv("LIARA_ENDPOINT"),
    aws_access_key_id=os.getenv("LIARA_ACCESS_KEY"),
    aws_secret_access_key=os.getenv("LIARA_SECRET_KEY"),
    region_name="us-east-1",
    config=C(signature_version="s3v4", connect_timeout=10, read_timeout=30),
)
bucket = os.getenv("LIARA_BUCKET", "voiceai")
key = "audio/_smoke_test.txt"
s3.put_object(Bucket=bucket, Key=key, Body=b"ok", ContentType="text/plain")
print("S3 upload OK:", key)
PY

echo "=== Done ==="
echo "Test: curl -X POST http://$(hostname -I | awk '{print $1}'):8000/jobs/voice-report ..."
