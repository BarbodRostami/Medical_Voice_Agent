# Voice Demo Checklist — ارائه صنعتی

هدف: نشان دادن مسیر **گوش و دهان صنعتی** (STT/TTS) در کنار مغز HakimAI، با مقایسهٔ قبل/بعد.

قرارداد HakimAI عوض نمی‌شود؛ فقط کیفیت متن گفتاری و موتور صدا بهتر می‌شود.

---

## ۱) پیش‌نیاز `.env`

حداقل برای دموی GapGPT:

```env
TTS_PROVIDER=openai
OPENAI_API_KEY=...
OPENAI_BASE_URL=https://api.gapgpt.app/v1
OPENAI_TTS_MODEL=gpt-4o-mini-tts
OPENAI_TTS_VOICE=nova
TTS_DIGIT_MODE=ascii
# اختیاری برای نمونهٔ ۳ (بهترین کیفیت متن):
# SPEECH_NORMALIZE_LLM=1
# OPENAI_SPEECH_LLM_MODEL=gpt-4o-mini
```

پیش‌فرض پروداکشن می‌تواند `TTS_PROVIDER=edge` بماند؛ دمو با فلگ/override اجرا می‌شود.

---

## ۲) ساخت پکیج A/B

از ریشهٔ پروژه:

```powershell
cd D:\Python_envs\rag_project
.\venv\Scripts\python.exe scripts\demo_voice_ab.py
.\venv\Scripts\python.exe scripts\demo_voice_ab.py --with-llm
```

خروجی: `assets/audio/demo/`

| فایل | معنی |
|------|------|
| `*__01_dict_edge.mp3` | لوکال edge + دیکشنری/phrasing |
| `*__02_dict_openai.mp3` | GapGPT TTS + دیکشنری/phrasing |
| `*__03_llm_openai.mp3` | GapGPT TTS + دیکشنری + LLM گفتاری (`--with-llm`) |

پخش:

```powershell
Invoke-Item "D:\Python_envs\rag_project\assets\audio\demo"
```

---

## ۳) اسکریپت ارائه (۳ دقیقه)

1. **مشکل:** اختصار خام / جمله خشک → صدای ضعیف  
2. **پخش 01** (edge) برای یک کیس vitals  
3. **پخش 02** (GapGPT + prep) — جهش کیفیت صدا  
4. **پخش 03** (اگر ساخته شده) — جمله روان‌تر مثل نمونهٔ دستی خوب  
5. **پیام معماری:** HakimAI = مغز · این سرور = STT/TTS با fallback لوکال  
6. **اطمینان:** اگر API قطع شود → edge؛ اگر LLM قطع شود → دیکشنری  

---

## ۴) چک‌لیست قبول کیفیت

برای هر کیس دمو:

- [ ] اعداد خوانده می‌شوند (۹۲ نه سکوت)
- [ ] SpO2/PEEP/ETCO2/MAP به فارسی درست‌اند
- [ ] ترتیب «اشباع اکسیژن بیمار…» طبیعی است (نه «بیمار اشباع…»)
- [ ] بدون لوپ «می می می»
- [ ] بدون کلید/خطای API، سیستم همچنان MP3 می‌دهد (edge)

---

## ۵) روی سرور شرکت

همان متغیرهای `.env` سرور + ری‌استارت سرویس.  
Smoke:

```bash
python scripts/smoke_voice_providers.py --tts --provider openai
python scripts/demo_voice_ab.py --with-llm
```

---

## ۶) مرحله بعد (اختیاری)

- `STT_PROVIDER=openai` اگر Whisper لوکال روی سرور ضعیف بود  
- چند کیس واقعی HakimAI ضبط‌شده در پوشهٔ demo  
- مقایسهٔ کور (بدون گفتن کدام فایل کدام موتور است) با همکار
