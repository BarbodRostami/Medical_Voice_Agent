import requests, time

BASE = 'http://localhost:8000'
r = requests.post(f'{BASE}/jobs/voice-report', json={'test': {'tafsir': 'بیمار با فشار خون پایین.', 'recom': 'ادامه مانیتورینگ.'}}, timeout=10)
job_id = r.json()['job_id']
print('Job submitted:', job_id[:8])

for i in range(15):
    time.sleep(5)
    s = requests.get(f'{BASE}/jobs/{job_id}', timeout=5).json()
    status = s['status']
    msg = s['message']
    print(f'[{(i+1)*5:>2}s] {status:12} | {msg}')
    if status in ('done', 'failed'):
        print('audio_url:', s.get('audio_url'))
        break
