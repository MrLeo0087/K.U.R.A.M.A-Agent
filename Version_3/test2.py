import sys
sys.path.append('..')

from langchain_groq import ChatGroq
from langchain_core.output_parsers import StrOutputParser
from state import KuramaState
from ddgs import DDGS
from dotenv import load_dotenv
from NODE.prompt import image_refiner_prompt
import os
import time

load_dotenv()

GROQ_API = os.getenv("GROQ_API_KEY")
llm = ChatGroq(model='llama-3.1-8b-instant', api_key=GROQ_API)
refine_chain = image_refiner_prompt | llm | StrOutputParser()
refine_query = refine_chain.invoke({'query':"Generate image of person that ride horse and save it and also open youtube and send message to mail",'task':'Generate iamge, person ride horse'})
print(refine_query)