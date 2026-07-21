import os
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import Chroma

# ۱. تنظیمات نام فایل و مسیر ذخیره‌سازی
FILE_NAME = "Critical_Care_Notes.pdf"
PERSIST_DIRECTORY = "db"

def main():
    # ۲. بررسی وجود فایل
    if not os.path.exists(FILE_NAME):
        print(f"❌ Error: {FILE_NAME} not found! Please check the filename.")
        return

    print(f"🔍 Loading PDF: {FILE_NAME}...")
    loader = PyPDFLoader(FILE_NAME)
    data = loader.load()
    print(f"✅ Loaded {len(data)} pages.")

    # ۳. تکه تکه کردن متن (Chunking)
    print("✂️ Splitting text into chunks...")
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=100,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    chunks = text_splitter.split_documents(data)
    print(f"✅ Created {len(chunks)} text chunks.")

    # ۴. ساخت Embeddings (استفاده از مدل رایگان HuggingFace)
    print("🧠 Generating Embeddings (this might take a moment)...")
    embeddings = HuggingFaceEmbeddings(model_name="ncbi/MedCPT-Article-Encoder")

    # ۵. ساخت و ذخیره پایگاه داده برداری (Vector Store)
    print("💾 Saving to Chroma DB...")
    vector_db = Chroma.from_documents(
        documents=chunks,
        embedding=embeddings,
        persist_directory=PERSIST_DIRECTORY
    )
    
    # در نسخه‌های جدید LangChain، متد persist() خودکار فراخوانی می‌شود
    print(f"🎉 Success! Ingestion complete. Database saved in '{PERSIST_DIRECTORY}' folder.")

if __name__ == "__main__":
    main()
