from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage
from dotenv import load_dotenv
import os

load_dotenv()
GROQ_API = os.getenv("GROQ_API_KEY")

llm = ChatGroq(model="groq/compound-mini", api_key=GROQ_API)
# compound-beta-mini
# compound-beta

messages = [
    SystemMessage(content="You are a concise assistant. Answer directly and briefly. No markdown, no headers, no step-by-step explanation. Just the answer."),
    HumanMessage(content="What is result of barcelona match and who they play today?")
]

response = llm.invoke(messages)
print(response.content)