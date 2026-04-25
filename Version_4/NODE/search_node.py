import sys
sys.path.append('..')

from langchain_groq import ChatGroq
from langchain_core.output_parsers import StrOutputParser
from NODE.state import KuramaState
from ddgs import DDGS
from dotenv import load_dotenv
from prompt import search_prompt,search_prompt2,compress_prompt,side_prompt
import os
import time

load_dotenv()

GROQ_API = os.getenv("GROQ_API_KEY")
SEARCH_LLM = "tavily"  # llm, ddgs, tavily



compress_llm = ChatGroq(model='llama-3.1-8b-instant', api_key=GROQ_API)


def safe_invoke(chain, inputs, retries=3, wait=20):
    for attempt in range(retries):
        try:
            return chain.invoke(inputs)
        except Exception as e:
            if '429' in str(e) or '413' in str(e):
                if attempt < retries - 1:
                    print(f"[KURAMA] Rate limit hit, waiting {wait}s...")
                    time.sleep(wait)
                else:
                    return "Search temporarily unavailable."
            else:
                return f"Error: {e}"


def make_search_node_llm(task):
    search_llm = ChatGroq(model="compound-beta-mini", api_key=GROQ_API)
    def node(state: KuramaState):
            try:
                time.sleep(task.id * 3)

                context = ""
                if task.depends_on:
                    for parent_id in task.depends_on:
                        parent_result = state['results'].get(parent_id, "")
                        context += f"Previous result: {parent_result}\n"

                query = state['query']
                task_content = task.content
                task_id = task.id

                chain1 = search_prompt | search_llm | StrOutputParser()
                raw_result = safe_invoke(chain1, {
                    'task': task_content,
                    'context': context[:300]
                })

                chain2 = compress_prompt | compress_llm | StrOutputParser()
                result = safe_invoke(chain2, {'raw_result': str(raw_result)[:1500]})

            except:
                result = f"Error in search note {task.content}"

    

            return {'results': {task_id: str(result)[:300]}}
    return node

def _execute_search_ddgs(query: str) -> str:
    try:
        with DDGS() as ddgs:
            results = [r for r in ddgs.text(query, region="wt-wt", max_results=5)]
        if not results:
            return "No search results found."
        return results
    except Exception as e:
        return f'Error: {e}'
    

def make_search_node_ddgs(task):
    search_llm = ChatGroq(model='llama-3.1-8b-instant', api_key=GROQ_API)
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

            refine_chain = side_prompt | search_llm | StrOutputParser()
            refine_query = refine_chain.invoke({'query':query,'task':task})
            web_results = _execute_search_ddgs(refine_query)

            chain = search_prompt2 | search_llm | StrOutputParser()
            result = safe_invoke(chain, {
                'task': task_content,
                'context': context,
                'web_result': web_results
            })

        except Exception as e:
            result = f"Error occure for {task_content} during search node"

        return {'results': {task_id: str(result)}}
    return node

def _execute_search_tavily(query: str) -> str:
    from tavily import TavilyClient
    tavily = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))
    try:
        response = tavily.search(query, search_depth="basic", max_results=3)
        if response.get('answer'):
            return response['answer']
        results = response.get('results', [])
        return "\n".join([r.get('content', '')[:200] for r in results])
    except Exception as e:
        return f'Error: {e}'

def make_search_node_tavily(task):
    search_llm = ChatGroq(model='llama-3.1-8b-instant', api_key=GROQ_API)
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
            web_results = _execute_search_tavily(task_content)

            chain = search_prompt2 | search_llm | StrOutputParser()
            result = safe_invoke(chain, {
                'task': task_content,
                'context': context[:300],
                'web_result': str(web_results)[:800]
            })
        except Exception as e:
            result = f"Error occure for {task_content} during search node"

        return {'results': {task_id: str(result)[:300]}}
    return node

if SEARCH_LLM == "llm":
    make_search_node = make_search_node_llm
elif SEARCH_LLM == "ddgs":
    make_search_node = make_search_node_ddgs
else:
    make_search_node = make_search_node_tavily