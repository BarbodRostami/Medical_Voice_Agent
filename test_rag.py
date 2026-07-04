from langchain_ollama import OllamaLLM
from langchain_chroma import Chroma
from langchain_community.document_loaders import PyPDFLoader

from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import Chroma

# تنظیمات مشابه فایل قبلی
PERSIST_DIRECTORY = "db"
embeddings = HuggingFaceEmbeddings(model_name="ncbi/MedCPT-Article-Encoder")

# بارگذاری دیتابیس ساخته شده
db = Chroma(persist_directory=PERSIST_DIRECTORY, embedding_function=embeddings)

# طرح یک سوال نمونه پزشکی از کتاب
query = "What are the primary signs of sepsis in critical care patients?"
docs = db.similarity_search(query, k=3)

print("\n--- نتایج جستجو در کتاب پزشکی ---")
for i, doc in enumerate(docs):
    print(f"\nبخش {i+1}:\n{doc.page_content[:500]}...")
