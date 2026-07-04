from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_chroma import Chroma
from langchain_ollama import OllamaLLM
import os
import uvicorn
import requests
import torch.nn as nn
import builtins

# رفع مشکل احتمالی در لود مدل‌های خاص
builtins.nn = nn 

app = FastAPI(title="Medical RAG API")

# --- تنظیمات ---
PERSIST_DIRECTORY = "db"  
EMBEDDING_MODEL = "sentence-transformers/all-mpnet-base-v2"
LLM_MODEL = "biomistral:latest" 

db = None
llm = None

print("🚀 Loading Vector Database and Models...")
try:
    embeddings = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)
    
    if not os.path.exists(PERSIST_DIRECTORY):
        print(f"⚠️ Warning: Folder '{PERSIST_DIRECTORY}' not found!")

    db = Chroma(persist_directory=PERSIST_DIRECTORY, embedding_function=embeddings)
    
    # تنظیم LLM با Stop Words برای کنترل بهتر خروجی
    llm = OllamaLLM(
        model=LLM_MODEL,
        base_url="http://host.docker.internal:11434",
        temperature=0.1,
        stop=["<|im_start|>", "<|im_end|>", "user:", "assistant:"]
    )
    print("✅ Models loaded successfully!")
except Exception as e:
    print(f"❌ Error during initialization: {e}")

class QuestionRequest(BaseModel):
    query: str

@app.get("/")
def home():
    return {"message": "Medical RAG API is running!", "model": LLM_MODEL, "db_loaded": db is not None}

@app.post("/chat")
async def chat(request: QuestionRequest):
    if db is None or llm is None:
        raise HTTPException(status_code=500, detail="Database or LLM not initialized.")

    try:
        query = request.query
        print(f"📩 Received question: {query}")
        
        # 1. جستجو در مستندات (RAG)
        docs = db.similarity_search(query, k=3)
        context = "\n\n".join([doc.page_content for doc in docs])

        # 2. ساخت پرامپت استاندارد ChatML
        prompt = (
            f"<|im_start|>system\n"
            f"You are a professional medical assistant. Use the following context to answer the user's question.\n"
            f"If the answer is not in the context, say 'I don't know based on the provided documents'.\n\n"
            f"Context: {context}<|im_end|>\n"
            f"<|im_start|>user\n"
            f"{query}<|im_end|>\n"
            f"<|im_start|>assistant\n"
        )

        print("🧠 Generating answer from BioMistral...")
        raw_answer = llm.invoke(prompt)
        
        # --- ۳. منطق تمیزکاری هوشمند و منعطف ---
        
        # الف) حذف تگ‌های چت و نقش‌ها
        clean_answer = raw_answer.replace("<|im_start|>", "").replace("<|im_end|>", "")
        clean_answer = clean_answer.replace("assistant", "").replace("user", "").replace("system", "")
        
        # ب) حذف عبارات نویز که معمولاً مدل در حالت Echo تکرار می‌کند
        noise_phrases = [
            "You are a professional medical assistant", 
            "Use the following context to answer",
            "Context:",
            query[:50] # حذف اگر شروع پاسخ شبیه شروع سوال باشد
        ]
        
        for phrase in noise_phrases:
            if phrase in clean_answer:
                # جدا کردن و برداشتن بخش بعد از عبارت نویز
                parts = clean_answer.split(phrase)
                clean_answer = parts[-1]

        # ج) پاکسازی نهایی (حذف فضاهای خالی و کاراکترهای اضافه)
        clean_answer = clean_answer.strip().lstrip(":").strip()
        
        # د) حذف کلمه "Answer:" اگر مدل تولید کرده باشد
        if clean_answer.lower().startswith("answer:"):
            clean_answer = clean_answer[7:].strip()

        # ه) سوپاپ اطمینان: اگر تمیزکاری باعث شد متن خیلی کوتاه یا خالی شود، 
        # همان متن خام را برگردان تا پاسخ مدل از دست نرود.
        if len(clean_answer) < 5:
            clean_answer = raw_answer.strip()
        
        # -------------------------------------------------------

        # 4. ارسال به جنگو برای ذخیره تاریخچه
               # 4. ارسال به جنگو برای ذخیره تاریخچه
    
        
            # --- ارسال به جنگو برای ذخیره در دیتابیس ---
        try:
            django_url = "http://django-admin:8000/save_chat/"
            payload = {"question": query, "answer": clean_answer}
            requests.post(django_url, json=payload, timeout=5)
        except Exception as e:
            print(f"❌ Connection to Django failed: {str(e)}")

    # ---------------------------------------
        return {
            "query": query,
            "answer": clean_answer,
            "source_documents_count": len(docs)
        }

    except Exception as e:
        print(f"💥 Error occurred: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
