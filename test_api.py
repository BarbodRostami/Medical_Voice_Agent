import requests
import json
import os
from dotenv import load_dotenv

load_dotenv()


api_key = os.getenv("OPENROUTER_API_KEY")

response = requests.post(
  url="https://openrouter.ai/api/v1/chat/completions",
  headers={
    # ۳. قرار دادن کلید به صورت امن در هدر درخواست
    "Authorization": f"Bearer {api_key}", 
  },
  data=json.dumps({
    "model": "google/gemini-flash-1.5-exp:free",
    "messages": [{"role": "user", "content": "Hello"}]
  })
)

print(response.status_code)
print(response.json())