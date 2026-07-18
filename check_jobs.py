import requests

from api_auth import request_headers

r = requests.get("http://localhost:8000/jobs", headers=request_headers(), timeout=5)
d = r.json()
print("Total jobs:", d["total"])
print()
for jid, j in d["jobs"].items():
    status = j["status"]
    msg = j["message"]
    print(f"Job: {jid}")
    print(f"  status  : {status}")
    print(f"  message : {msg}")
    if j.get("audio_url"):
        print(f"  audio_url: {j['audio_url']}")
    if j.get("answer"):
        print(f"  answer  : {j['answer'][:150]}...")
    if j.get("error"):
        print(f"  error   : {j['error']}")
    print()
