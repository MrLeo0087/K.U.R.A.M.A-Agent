from typing import Dict, Any
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_groq import ChatGroq
from state import KuramaState

SIMPLE_GENERAL_PROMPT = """You are a helpful, direct conversational assistant. 
Answer the user's question accurately, concisely, and factually. 
Do not add fluff, greetings, or dramatic intro/outro text."""


def general_query_node(state: KuramaState, task_id: int = 0) -> Dict[str, Any]:
    """Executes simple conversational queries and stores the factual response in state['results']."""
    llm = ChatGroq(model="llama-3.1-8b-instant", temperature=0.3)

    user_query = state.get("query", "")
    context_str = state.get("context", "")

    messages = [
        SystemMessage(content=SIMPLE_GENERAL_PROMPT),
    ]

    if context_str:
        messages.append(SystemMessage(content=f"Context:\n{context_str}"))

    messages.append(HumanMessage(content=user_query))

    try:
        response = llm.invoke(messages)
        return {
            "results": {task_id: response.content}
        }
    except Exception as e:
        return {
            "failed_tasks": [task_id],
            "results": {task_id: f"Error executing general query: {str(e)}"}
        }

if __name__ == '__main__':
    while True:
        user = input('Enter your query: ')
        state: KuramaState = {
            "query": user,
            "tasks": [],
            "results": {},
            "failed_tasks": [],
            "context": "",
            "final_response": None,
        }
        result = general_query_node(state)
        print(f"KURAMA:\n{result.get('results')}")