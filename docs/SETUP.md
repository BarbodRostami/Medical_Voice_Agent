# Medical Voice Agent — Setup Guide

## پیش‌نیازها

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) نصب باشه
- حداقل **8 GB RAM** (برای مدل biomistral)
- حداقل **10 GB فضای دیسک**

---

## ۱. کلون کردن پروژه

```bash
git clone https://github.com/behinmed/medical-voice-agent.git
cd medical-voice-agent
```

---

## ۲. تنظیم فایل env

```bash
cp .env.example .env
```

فایل `.env` رو باز کن و مقادیر زیر رو پر کن:

```
LIARA_ENDPOINT=https://sas.amin.parminstorage.ir
LIARA_BUCKET=voiceai
LIARA_ACCESS_KEY=کلید_دسترسی_شما
LIARA_SECRET_KEY=کلید_مخفی_شما

# آدرس عمومی API برای لینک audio_url (روی سرور شرکت IP بزنید)
PUBLIC_API_URL=http://192.168.1.15:8000
```

> کلیدهای Parmin Cloud از پنل Parmin بگیرید — **نه** GitHub token.

---

## ۳. اجرای پروژه

### با Docker
```bash
docker compose up -d
```

### لوکال (برای دیدن لاگ در ترمینال)
از ریشهٔ پروژه:
```powershell
cd d:\Python_envs\rag_project
.\venv\Scripts\python.exe -m uvicorn backend.main_api:app --host 0.0.0.0 --port 8000 --log-level info
```

> اولین بار با Docker حدود **10-20 دقیقه** طول میکشه:
> - image‌های Docker دانلود میشن
> - مدل `biomistral` (~4 GB) از Ollama دانلود میشه

---

## ۴. بررسی وضعیت

```bash
# دیدن وضعیت همه سرویس‌ها
docker compose ps

# دیدن لاگ‌ها
docker compose logs -f

# لاگ فقط backend
docker compose logs -f backend
```

---

## ۵. دسترسی به سرویس‌ها

| سرویس | آدرس |
|-------|-------|
| API (FastAPI) | http://localhost:8000 |
| UI (Streamlit) | http://localhost:8501 |
| Admin Panel | http://localhost:8001 |
| Ollama | http://localhost:11434 |

---

## ۷. API برای همکار فرانت‌اند

مستندات تعاملی: **http://SERVER_IP:8000/docs**

قرارداد سرور خارجی / HakimAI: فایل **[COLLABORATOR_API.md](COLLABORATOR_API.md)**  

- **TTS:** `POST /api/ask` → HakimAI فایل MP3 را مستقیم از S3 پول می‌کند (`s3_key`)  
- **STT:** `POST /api/cases` + فایل → متن با `GET /api/get-msg?uuid=`

### جریان async (پیشنهادی)

اگر `API_KEY` در `.env` ست شده، همه درخواست‌ها (به‌جز `GET /` و پخش `/voice/audio/...`) باید هدر داشته باشند:

```
X-API-Key: <your-api-key>
```

```bash
# ۱) ارسال درخواست — فوری job_id برمی‌گردد
POST /jobs/voice-report
Content-Type: application/json
X-API-Key: <your-api-key>
{"uuid": {"tafsir": "...", "recom": "..."}}

POST /jobs/chat
X-API-Key: <your-api-key>
{"query": "What is the normal ETCO2 range?"}

POST /stt/ask
Content-Type: multipart/form-data
X-API-Key: <your-api-key>
file: (فایل صوتی MP3/WAV — فارسی)

# ۲) بررسی وضعیت — هر ۳-۵ ثانیه
GET /jobs/{job_id}
X-API-Key: <your-api-key>

# ۳) وقتی status=done شد
# audio_url → لینک پخش MP3 (مسیر: .../voice/audio/{uuid}.mp3 — بدون نیاز به API key در مرورگر)# answer → پاسخ فارسی (در /jobs/chat و /stt/ask)
```

### آدرس سرور شرکت (تست‌شده)

| مورد | مقدار |
|------|--------|
| Base URL | `http://192.168.1.15:8000` |
| Swagger | `http://192.168.1.15:8000/docs` |
| Auth header | `X-API-Key` (اگر `API_KEY` در `.env` ست شده باشد) |

### Postman Collection (تحویل به فرانت)

فایل‌های آماده در پوشه `postman/`:

| فایل | کاربرد |
|------|--------|
| `Medical_Voice_Agent.postman_collection.json` | همه endpointها + auto-save `job_id` |
| `Medical_Voice_Agent.postman_environment.json` | متغیر `base_url` و `job_id` |

**Import در Postman:**
1. **Import** → هر دو فایل JSON را انتخاب کنید
2. Environment **Medical Voice Agent — Company Server** را فعال کنید
3. از folder **02 — Async Jobs** شروع کنید

**Share با همکار:** فایل‌های `postman/*.json` را بفرستید یا Collection را Export/Share کنید.

---

## ۶. Deploy روی سرور Linux (شرکت)

### پیش‌نیاز

- Ubuntu/Debian با Docker و docker-compose v1 (`docker-compose` با خط تیره)
- Ollama روی **host** (نه داخل Docker) با مدل `biomistral`
- دسترسی شبکه به Parmin Cloud (`sas.amin.parminstorage.ir`)

### Branch

```bash
git clone https://github.com/behinmed/medical-voice-agent.git
cd medical-voice-agent
git fetch origin
git checkout feature/async-stt-jobs   # یا chore/dockerize
git pull origin feature/async-stt-jobs
```

### فایل `.env` روی سرور

```bash
cp .env.example .env
# مقادیر LIARA_* و PUBLIC_API_URL را پر کنید
```

### Ollama روی Linux

در `docker-compose.yml` مقدار `OLLAMA_HOST` را عوض کنید:

```yaml
- OLLAMA_HOST=http://172.17.0.1:11434
```

```bash
sed -i.bak 's|host.docker.internal|172.17.0.1|' docker-compose.yml
```

### Build و اجرا

```bash
sudo docker-compose build --no-cache backend
sudo docker-compose down
sudo docker rm -f medical_voice_agent_backend_1 2>/dev/null || true
sudo docker-compose up -d backend
```

> اگر خطای `KeyError: ContainerConfig'` دیدید، حتماً قبل از `up` کانتینر قدیمی را `down` + `rm -f` کنید.

### تست S3 (Parmin)

```bash
sudo docker-compose exec -T backend python -c "
import os, boto3
from botocore.config import Config as C
s3 = boto3.client('s3',
    endpoint_url=os.getenv('LIARA_ENDPOINT'),
    aws_access_key_id=os.getenv('LIARA_ACCESS_KEY'),
    aws_secret_access_key=os.getenv('LIARA_SECRET_KEY'),
    region_name='us-east-1',
    config=C(signature_version='s3v4', connect_timeout=10, read_timeout=30))
s3.put_object(Bucket=os.getenv('LIARA_BUCKET','voiceai'), Key='audio/_smoke_test.txt', Body=b'ok')
print('S3 upload OK')
"
```

### تست job و audio_url

```bash
curl -X POST http://localhost:8000/jobs/voice-report \
  -H "Content-Type: application/json" \
  -d '{"tafsir":"تست","recom":"تست"}'

curl http://localhost:8000/jobs/<job_id>
```

وقتی `status=done` شد، `audio_url` را در مرورگر باز کنید.

### Deploy از ویندوز (اختیاری)

```powershell
powershell -ExecutionPolicy Bypass -File scripts/deploy_to_server.ps1
```

اسکریپت `.env` را به سرور می‌فرستد و `scripts/server_setup.sh` را اجرا می‌کند.
اگر SSH بدون کلید است، دستورات manual را چاپ می‌کند.

> فایل `server_setup.sh` باید با **LF** (نه CRLF) باشد. روی سرور:  
> `sed -i 's/\r$//' scripts/server_setup.sh`

---

## ۸. متوقف کردن پروژه

```bash
# متوقف کردن (بدون حذف داده‌ها)
docker compose stop

# متوقف و حذف کانتینرها
docker compose down

# حذف کامل همه چیز شامل مدل Ollama
docker compose down -v
```

---

## رفع مشکلات رایج

**مشکل: backend راه نمیفته**
```bash
docker compose logs backend
# اگه Ollama آماده نشده، چند دقیقه صبر کن
docker compose restart backend
```

**مشکل: مدل دانلود نشده**
```bash
docker compose exec ollama ollama pull biomistral
```

**مشکل: پورت در حال استفاده**
```bash
# ببین چه چیزی روی پورت 8000 هست
netstat -ano | findstr :8000   # Windows
lsof -i :8000                  # Mac/Linux
```

**مشکل: audio_url برمی‌گردد ولی 404 در مرورگر**
- `audio_url` را دقیقاً از poll کپی کنید (یک کاراکتر اشتباه = 404)
- مسیر صحیح: `.../voice/audio/{uuid}.mp3`

**مشکل: ModuleNotFoundError: boto3 داخل کانتینر**
- branch قدیمی (`main`) است — به `feature/async-stt-jobs` بروید
- `sudo docker-compose build --no-cache backend` بزنید

**مشکل: S3 از ایران (لوکال) timeout**
- از ایران Parmin ممکن است در دسترس نباشد؛ روی سرور شرکت تست کنید
