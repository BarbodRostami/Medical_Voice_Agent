"""List all files in Parmin Cloud bucket."""
import boto3
import os
from dotenv import load_dotenv

load_dotenv()

s3 = boto3.client(
    "s3",
    endpoint_url=os.getenv("LIARA_ENDPOINT"),
    aws_access_key_id=os.getenv("LIARA_ACCESS_KEY"),
    aws_secret_access_key=os.getenv("LIARA_SECRET_KEY"),
    region_name="us-east-1",
)
bucket = os.getenv("LIARA_BUCKET", "voiceai")

resp = s3.list_objects_v2(Bucket=bucket)
objects = resp.get("Contents", [])

if not objects:
    print("باکت خالیه یا فایلی وجود نداره.")
else:
    print(f"تعداد فایل‌ها: {len(objects)}\n")
    print(f"{'نام فایل':<60} {'حجم':>10}  {'تاریخ'}")
    print("-" * 90)
    for obj in sorted(objects, key=lambda x: x["LastModified"], reverse=True):
        size_kb = obj["Size"] / 1024
        print(f"{obj['Key']:<60} {size_kb:>8.1f} KB  {obj['LastModified'].strftime('%Y-%m-%d %H:%M')}")
