#!/bin/bash
# Run on company server after .env is in place.
# Usage: bash scripts/server_setup.sh [/path/to/Medical_Voice_Agent]
set -euo pipefail

PROJECT_DIR="${1:-$HOME/Medical_Voice_Agent}"
BRANCH="${DEPLOY_BRANCH:-feature/external-cases-api}"
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
# Company VM must advertise its own LAN IP (not a laptop IP).
if grep -qE '^PUBLIC_API_URL=http://192\.168\.1\.235' .env 2>/dev/null; then
  sed -i.bak 's|^PUBLIC_API_URL=.*|PUBLIC_API_URL=http://192.168.1.15:8000|' .env
  echo "Corrected PUBLIC_API_URL to http://192.168.1.15:8000"
fi
# Whisper defaults safe for CPU VMs (avoid CUDA float16 crashes)
grep -q '^WHISPER_MODEL_SIZE=' .env 2>/dev/null || echo 'WHISPER_MODEL_SIZE=medium' >> .env
grep -q '^WHISPER_DEVICE=' .env 2>/dev/null || echo 'WHISPER_DEVICE=cpu' >> .env
grep -q '^WHISPER_COMPUTE_TYPE=' .env 2>/dev/null || echo 'WHISPER_COMPUTE_TYPE=int8' >> .env
if grep -q "LIARA_ACCESS_KEY=ghp_" .env 2>/dev/null; then
  echo "ERROR: LIARA_ACCESS_KEY looks like a GitHub token — use Parmin Cloud keys"
  exit 1
fi

echo "=== Git pull ($BRANCH) ==="
# Ensure company remote (behinmed) exists — laptop pushes feature branches there.
if ! git remote get-url company >/dev/null 2>&1; then
  git remote add company https://github.com/behinmed/medical-voice-agent.git || true
fi
if git remote get-url company >/dev/null 2>&1; then
  REMOTE=company
elif git remote get-url origin >/dev/null 2>&1; then
  REMOTE=origin
else
  echo "ERROR: no git remote configured"
  exit 1
fi
echo "Using remote: $REMOTE"
git fetch "$REMOTE"
git checkout "$BRANCH" || git checkout -b "$BRANCH" "$REMOTE/$BRANCH"
git pull --ff-only "$REMOTE" "$BRANCH" || git reset --hard "$REMOTE/$BRANCH"

echo "=== Ollama host (Linux server) ==="
if grep -q 'OLLAMA_HOST=http://host.docker.internal:11434' docker-compose.yml 2>/dev/null; then
  sed -i.bak 's|OLLAMA_HOST=http://host.docker.internal:11434|OLLAMA_HOST=http://172.17.0.1:11434|' docker-compose.yml
  echo "Set OLLAMA_HOST to 172.17.0.1 for Linux"
fi

echo "=== Docker rebuild backend ==="
if command -v docker-compose >/dev/null 2>&1; then
  COMPOSE="sudo docker-compose"
else
  COMPOSE="sudo docker compose"
fi
$COMPOSE up -d --build backend

echo "=== Health check ==="
sleep 12
curl -sf http://localhost:8000/ | head -c 300
echo ""

echo "=== S3 upload smoke test ==="
$COMPOSE exec -T backend python - <<'PY'
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
echo "API: http://192.168.1.15:8000/"
echo "Docs: http://192.168.1.15:8000/docs"
