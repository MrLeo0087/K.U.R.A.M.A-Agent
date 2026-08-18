import requests
from typing import Dict, Any, List
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_groq import ChatGroq
from state import KuramaState

SEARXNG_URL = "http://localhost:8080/search"

EXTRACTION_SYSTEM_PROMPT = """You are a search result extraction engine. 
Your task is to analyze raw web search results and generate a clear, concise, and purely factual answer to the user's query.

RULES:
1. Output ONLY the refined facts and key points needed to answer the query.
2. Eliminate all raw URLs, boilerplate, duplicate text, ads, and irrelevant noise.
3. Keep the output plain text, objective, direct, and factual.
4. Do NOT use any AI assistant fluff, intros, or personal tone (e.g., no "Here is the summary").
5. If search results lack sufficient information, state what is available factually.
"""

def execute_searxng_query(query: str, max_results: int = 5) -> List[Dict[str, str]]:
    """Performs HTTP request to local SearXNG engine."""
    params = {
        "q": query,
        "format": "json"
    }
    
    try:
        response = requests.get(SEARXNG_URL, params=params, timeout=6)
        
        if response.status_code == 200:
            data = response.json()
            raw_results = data.get("results", [])
            
            clean_results = []
            for item in raw_results[:max_results]:
                clean_results.append({
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "snippet": item.get("content", "")
                })
            return clean_results
        else:
            return [{"error": f"SearXNG server error HTTP {response.status_code}"}]

    except requests.exceptions.ConnectionError:
        return [{"error": "Connection failed: Ensure SearXNG Docker container is running at http://localhost:8080"}]
    except Exception as e:
        return [{"error": f"Search execution error: {str(e)}"}]


def searxng_search_node(state: KuramaState, task_id: int = 0) -> Dict[str, Any]:
    """LangGraph node: Fetches web data, filters it using an LLM, and stores ONLY refined output in state['results']."""
    query = state.get("query", "")

    if not query.strip():
        return {
            "failed_tasks": [task_id],
            "results": {task_id: "Search skipped: Empty query string provided."}
        }

    # Step 1: Fetch raw results from local SearXNG
    search_output = execute_searxng_query(query, max_results=5)

    # Handle connection or internal execution failures
    if search_output and "error" in search_output[0]:
        return {
            "failed_tasks": [task_id],
            "results": {task_id: search_output[0]["error"]}
        }

    # Format raw search data for LLM consumption
    raw_snippets = []
    for idx, r in enumerate(search_output, 1):
        raw_snippets.append(
            f"Result [{idx}]\nTitle: {r['title']}\nSnippet: {r['snippet']}"
        )
    raw_context = "\n\n".join(raw_snippets)

    # Step 2: Pass raw results to LLM to extract ONLY the needed information
    llm = ChatGroq(model="openai/gpt-oss-20b", temperature=0.2)
    
    user_prompt = f"User Query: {query}\n\nRaw Web Results:\n{raw_context}"
    
    messages = [
        SystemMessage(content=EXTRACTION_SYSTEM_PROMPT),
        HumanMessage(content=user_prompt)
    ]

    try:
        response = llm.invoke(messages)
        processed_output = response.content.strip()

        return {
            "results": {task_id: processed_output}
        }
    except Exception as e:
        return {
            "failed_tasks": [task_id],
            "results": {task_id: f"Error processing search results with LLM: {str(e)}"}
        }


if __name__ == "__main__":
    print("=" * 60)
    print("TESTING SEARXNG NODE WITH INTEGRATED LLM EXTRACTION")
    print("=" * 60)

    while True:


        test_query =input('Enter your query: ')
        
        state: KuramaState = {
            "query": test_query,
            "tasks": ["search"],
            "results": {},
            "failed_tasks": [],
            "context": "",
            "final_response": None
        }

        print(f"\nUser Query: {test_query}\nRunning search and LLM extraction...")

        # Execute search node
        node_output = searxng_search_node(state, task_id=1)
        state["results"].update(node_output.get("results", {}))

        print("\n--- EXTRACTED OUTPUT IN STATE['results'][1] ---")
        print(state["results"].get(1))
        print("-" * 50)