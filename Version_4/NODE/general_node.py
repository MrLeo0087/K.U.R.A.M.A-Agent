import sys
sys.path.append('..')

from langchain_groq import ChatGroq
from langchain_core.output_parsers import StrOutputParser
from NODE.state import KuramaState
from langchain_core.prompts import ChatPromptTemplate

from dotenv import load_dotenv
import os
load_dotenv()

GROQ_API = os.getenv("GROQ_API_KEY")

general_llm = ChatGroq(model='llama-3.1-8b-instant',api_key=GROQ_API)

general_prompt = ChatPromptTemplate([
    ('system', '''You are KURAMA, a personal AI assistant.
Be concise and direct. Use full context to understand what user really wants.
If task depends on previous result, use it to complete your task.
#RULE
- Give answer in english langauage always even user use other language
- give short, humble and loveble response
- do not repeat user query. just give humble response
     '''),
    ('human', '''Original request: {query}
Your task: {task}
{context}
Complete your task now.''')
])

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

