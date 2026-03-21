from langchain_ollama import ChatOllama
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_groq import ChatGroq
from dotenv import load_dotenv
import os

load_dotenv()

GROQ_API_KEY = os.getenv('GROQ_API_KEY')

def gemini_model():
    return ChatGoogleGenerativeAI(model = 'gemini-2.0-flash-lite'), 'Gemini model use'

def ollama_model():
    return ChatOllama(model='qwen2.5:3b'),'Ollama model use'

def groq_model():
    return ChatGroq(model='llama-3.1-8b-instant',api_key=GROQ_API_KEY),'Use groq'


gemini_llm, message1 = gemini_model()
ollama_llm, message2 = ollama_model()
groq_llm, message3 = groq_model()

query = "Hello, How are you ?"

try:
    result = gemini_llm.invoke(query)
    print(f'{result.content}\n\n{message1}')

except:
    try:
        result = groq_llm.invoke(query)
        print(f'{result.content}\n\n{message3}')

    except:
        result = ollama_llm.invoke(query)
        print(f'{result.content}\n\n{message1}')