from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.llms import Ollama

# تنظیمات اصلی
# نام مدلی که در Ollama ساختید
LLM_MODEL = "biomistral" 
# مدل Embedding که برای ساخت دیتابیس استفاده شد
EMBEDDING_MODEL = "ncbi/MedCPT-Query-Encoder"
PERSIST_DIRECTORY = "db"

def start_chat():
    print("\n--- 🏥 Medical RAG System (BioMistral + MedCPT) ---")
    
    # ۱. بارگذاری دیتابیس برداری (آفلاین)
    print("🔄 Loading Vector Database...")
    embeddings = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)
    db = Chroma(persist_directory=PERSIST_DIRECTORY, embedding_function=embeddings)
    
    # ۲. اتصال به مدل BioMistral در Ollama
    print(f"🚀 Connecting to Ollama ({LLM_MODEL})...")
    llm = Ollama(model=LLM_MODEL)
    
    while True:
        query = input("\n💉 Enter medical question (or 'exit'): ")
        if query.lower() in ['exit', 'quit', 'q']:
            break
            
        print("🔍 Searching PDF context...")
        # پیدا کردن ۲ بخش مرتبط از فایل PDF
        docs = db.similarity_search(query, k=2)
        context = "\n\n".join([doc.page_content for doc in docs])
        
        # ۳. ساخت پرامپت و دریافت پاسخ
        print("🤖 BioMistral is analyzing...")
        prompt = f"""
        You are a medical assistant. Use the provided context to answer the question.
        Context: {context}
        
        Question: {query}
        
        Answer (based ONLY on context):"""
        
        try:
            answer = llm.invoke(prompt)
            print(f"\n💡 FINAL ANSWER:\n{answer}")
        except Exception as e:
            print(f"❌ Error: {e}")

if __name__ == "__main__":
    start_chat()
