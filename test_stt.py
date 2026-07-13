"""Test the STT voice input endpoint: POST /stt/ask"""
import asyncio, time, requests, edge_tts

BASE = 'http://localhost:8000'

# Step 1: generate a test MP3 with a medical question (English)
async def make_test_audio():
    comm = edge_tts.Communicate("What is the normal ETCO2 range in capnography?", voice="en-US-JennyNeural")
    await comm.save("test_voice_input.mp3")

print("Creating test audio file...")
asyncio.run(make_test_audio())
print("test_voice_input.mp3 created.")

# Step 2: submit to /stt/ask
print("\nSubmitting to POST /stt/ask ...")
with open("test_voice_input.mp3", "rb") as f:
    r = requests.post(f"{BASE}/stt/ask", files={"file": ("question.mp3", f, "audio/mpeg")}, timeout=15)

print(f"Response ({r.status_code}):", r.json())
job_id = r.json()["job_id"]
print(f"Job ID: {job_id[:8]}...")

# Step 3: poll until done
print("\nPolling for result...")
for i in range(60):
    time.sleep(5)
    s = requests.get(f"{BASE}/jobs/{job_id}", timeout=5).json()
    status = s["status"]
    msg = s["message"]
    print(f"[{(i+1)*5:>3}s] {status:12} | {msg}")
    if status in ("done", "failed"):
        print("\n--- FINAL RESULT ---")
        print("transcription:", s.get("transcription", "N/A"))
        if s.get("answer"):
            print("answer:", s["answer"][:200], "...")
        print("audio_url:", s.get("audio_url"))
        if s.get("error"):
            print("error:", s["error"])
        break
