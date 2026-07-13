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
```

---

## ۳. اجرای پروژه

```bash
docker compose up -d
```

> اولین بار حدود **10-20 دقیقه** طول میکشه:
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

### جریان async (پیشنهادی)

```bash
# ۱) ارسال درخواست — فوری job_id برمی‌گردد
POST /jobs/voice-report
Content-Type: application/json
{"uuid": {"tafsir": "...", "recom": "..."}}

POST /jobs/chat
{"query": "What is the normal ETCO2 range?"}

POST /stt/ask
Content-Type: multipart/form-data
file: (فایل صوتی MP3/WAV — فارسی)

# ۲) بررسی وضعیت — هر ۳-۵ ثانیه
GET /jobs/{job_id}

# ۳) وقتی status=done شد
# audio_url → لینک پخش MP3
# answer → پاسخ فارسی
```

### روی سرور Linux

در `docker-compose.yml` مقدار `OLLAMA_HOST` را عوض کنید:

```yaml
- OLLAMA_HOST=http://172.17.0.1:11434
```

سپس:

```bash
sudo docker compose pull
sudo docker compose up -d --build backend
```

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
