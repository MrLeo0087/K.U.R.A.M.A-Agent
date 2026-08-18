from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate
from dotenv import load_dotenv
from state import KuramaState

load_dotenv()

SYSTEM_PROMPT = 'You are helpful ai assitance. give answer of user query in short and direct. be humble and nice.'

def general_node(state:KuramaState,task_id:int = 0):
    user_query = state.get('query')

