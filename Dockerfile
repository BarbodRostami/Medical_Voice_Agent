# استفاده از نسخه سبک پایتون
FROM python:3.10-slim

# تنظیم دایرکتوری کاری در کانتینر
WORKDIR /app

# نصب ابزارهای مورد نیاز برای ساخت برخی پکیج‌های پایتونی
RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# کپی کردن فایل نیازمندی‌ها
COPY requirements.txt .

# نصب کتابخانه‌ها
RUN pip install --no-cache-dir -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple


# کپی کردن بقیه کدها و دیتابیس (پوشه db) به داخل کانتینر
COPY . .

# باز کردن پورت 8000 برای FastAPI
EXPOSE 8000

# دستور اجرای سرور
CMD ["python", "main_api.py"]
