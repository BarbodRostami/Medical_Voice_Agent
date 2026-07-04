import os
import re
import subprocess
import arabic_reshaper
from bidi.algorithm import get_display
from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.llms import Ollama
from deep_translator import GoogleTranslator

# --- تنظیمات سیستم ---
PIPER_MODEL = "fa_IR-amir-medium.onnx"
LLM_MODEL = "biomistral"
EMBEDDING_MODEL = "ncbi/MedCPT-Query-Encoder"
PERSIST_DIRECTORY = "db"

# ۱. تنظیمات مترجم
translator_to_en = GoogleTranslator(source='fa', target='en')
translator_to_fa = GoogleTranslator(source='en', target='fa')

def fix_farsi_display(text):
    """اصلاح نمایش فارسی در ترمینال"""
    return get_display(arabic_reshaper.reshape(text))

def speak_farsi_offline(text):
    """تولید صدای فارسی با استفاده از فایل واسط برای رفع مشکل Encoding"""
    output_wav = "response.wav"
    temp_txt = "input_text.txt"
    
    try:
        # ۱. پاکسازی متن از کاراکترهای غیرمجاز
        clean_text = text.replace('"', '').replace("'", "").replace("\n", " ")
        
        # ۲. ذخیره متن در یک فایل با کدگذاری utf-8 (بسیار مهم)
        with open(temp_txt, "w", encoding="utf-8") as f:
            f.write(clean_text)
        
        # ۳. اجرای Piper با خواندن از فایل به جای echo
        # دستور: piper --model fa_IR-amir-medium.onnx --input_file input_text.txt --output_file response.wav
        command = f'piper --model {PIPER_MODEL} --input_file {temp_txt} --output_file {output_wav} --length_scale 1.1'
        
        print(f"DEBUG: Running Piper...") # برای اطمینان از اجرا
        result = subprocess.run(command, shell=True, capture_output=True, text=True)
        
        if result.returncode != 0:
            print(f"❌ Piper Error: {result.stderr}")
            return

        # ۴. پخش فایل صوتی
        if os.path.exists(output_wav):
            # استفاده از روش مستقیم‌تر برای پخش
            os.system(f"start /min powershell -c (New-Object Media.SoundPlayer '{output_wav}').PlaySync()")
            
    except Exception as e:
        print(f"\n❌ خطا در فرآیند پخش صدا: {e}")
    finally:
        # پاکسازی فایل موقت متنی (اختیاری)
        if os.path.exists(temp_txt):
            os.remove(temp_txt)

print(fix_farsi_display("--- در حال بارگذاری دانش پزشکی (کمی صبر کنید) ---"))

# ۲. بارگذاری بانک اطلاعاتی و مدل هوش مصنوعی
embeddings = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)
vectorstore = Chroma(persist_directory=PERSIST_DIRECTORY, embedding_function=embeddings)
llm = Ollama(model=LLM_MODEL)

def medical_voice_rag():
    print("\n" + "="*50)
    print(fix_farsi_display("🏥 دستیار صوتی پزشکی با صدای طبیعی فارسی"))
    print("="*50)

    while True:
        user_input = input("\n❓ " + fix_farsi_display("سوال خود را بپرسید: "))
        
        if user_input.lower() in ['exit', 'quit', 'خروج']:
            break

        try:
            # الف. جستجو در اسناد
            print(fix_farsi_display("🔍 در حال تحلیل منابع تخصصی..."))
            query_eng = translator_to_en.translate(user_input)
            docs = vectorstore.similarity_search(query_eng, k=3)
            context = "\n".join([doc.page_content for doc in docs])

            # ب. تولید پاسخ علمی
            prompt = f"Context: {context}\nQuestion: {query_eng}\nAnswer clearly in English:"
            raw_response = llm.invoke(prompt)
            
            # ج. ترجمه به فارسی
            persian_response = translator_to_fa.translate(raw_response)
            
            print("\n" + "-"*30)
            print(fix_farsi_display(f"🇮🇷 پاسخ: {persian_response}"))
            print("-"*30)

            # د. پخش صوتی فارسی
            print(fix_farsi_display("🔊 در حال قرائت پاسخ..."))
            speak_farsi_offline(persian_response)

        except Exception as e:
            print(f"❌ خطا: {e}")

if __name__ == "__main__":
    medical_voice_rag()
