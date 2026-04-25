import sys
sys.path.append('..')

from langchain_groq import ChatGroq
from langchain_core.output_parsers import StrOutputParser
from state import KuramaState
from NODE.prompt import general_prompt,search_prompt

from dotenv import load_dotenv
import os
load_dotenv()

GROQ_API = os.getenv("GROQ_API_KEY")

general_llm = ChatGroq(model='llama-3.1-8b-instant',api_key=GROQ_API)

def make_general_node(task):
    def node(state: KuramaState):
        try:
            context = ""
            if task.depends_on:
                for parent_id in task.depends_on:
                    parent_result = state['results'].get(parent_id, "")
                    context += f"Previous result: {parent_result}\n"

            query = state['query']
            task_content = task.content    
            task_id = task.id              
                
            chain = general_prompt | general_llm | StrOutputParser()
            result = chain.invoke({'query': query, 'task': task_content,'context':context[:500]})
        except:
            result = f"Cannot complete {task_content} sir"
            
        return {'results': {task_id: result}}
    return node

