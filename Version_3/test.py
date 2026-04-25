from langchain_google_genai import ChatGoogleGenerativeAI

from dotenv import load_dotenv
load_dotenv()
import os

GEMINI_API = os.getenv('GOOGLE_API_KEY')

test_llm  = ChatGoogleGenerativeAI(
        model="gemini-2.0-flash-lite",
        google_api_key=GEMINI_API
    )

result = test_llm.invoke("Hello")
print(result.content)