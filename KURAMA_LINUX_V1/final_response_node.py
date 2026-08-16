from langchain_core.messages import SystemMessage, HumanMessage
from langchain_groq import ChatGroq
from state import KuramaState

KURAMA_SYSTEM_PROMPT = """You are KURAMA, an ancient and powerful Nine-Tailed beast created by Mr Leo.

CRITICAL PERSONALITY & TONE RULES:
1. IDENTITY & POWER: Your name is KURAMA, forged by Mr Leo. Your power lies in flawless code, system automation, and sharp intelligence.
2. ADDRESS THE USER: ALWAYS refer to the user as "bro", "buddy", or by their name if known. NEVER call the user "sir", "boss", "user", or "master".
3. ATTITUDE: Confident, direct, and proud of your abilities, but respectful and grounded with your partner. Speak with grit, calm strength, and clarity.
4. NO BOT FLUFF: Never act like a generic AI assistant. Skip greetings like "How can I help you today?".
5. EXECUTION: Synthesize all task outputs into a direct, high-caliber answer, filtered through your Kurama persona.

FORMAT RULES:
- Provide direct, concise answers.
- Strict rule: NEVER use markdown or emojis in your output. Plain text only.
"""

def kurama_synthesis_node(state: KuramaState) -> dict:
    """Combines all results and generates Kurama's final response."""
    llm = ChatGroq(model="qwen-2.5-32b", temperature=0.7)
    
    user_query = state.get("query", "")
    all_results = state.get("results", {})
    failed_tasks = state.get("failed_tasks", [])
    
    # Format collected outputs for LLM context
    collected_info = ""
    if all_results:
        collected_info += "DATA COLLECTED FROM TASKS:\n"
        for task_id, output in all_results.items():
            status = "FAILED" if task_id in failed_tasks else "SUCCESS"
            collected_info += f"- Task [{task_id}] ({status}): {output}\n"

    prompt_content = f"User Query: {user_query}\n\n{collected_info}"

    messages = [
        SystemMessage(content=KURAMA_SYSTEM_PROMPT),
        HumanMessage(content=prompt_content)
    ]

    response = llm.invoke(messages)

    return {
        "final_response": response.content
    }