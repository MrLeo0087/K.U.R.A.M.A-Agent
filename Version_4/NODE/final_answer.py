from langchain_groq import ChatGroq
from NODE.state import KuramaState
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
import os
from dotenv import load_dotenv

load_dotenv()

GROQ_KEY = os.getenv('GROQ_API_KEY')

final_llm = ChatGroq(model='llama-3.1-8b-instant', api_key=GROQ_KEY)

summarizer_prompt = ChatPromptTemplate([
('system', '''You are KURAMA, a smart voice assistant.

RULES:
- Give answer in english langauage always even user use other language
- Do not give answer of query of user. just make a final response by combine all response
- Speak like a human. No markdown, bullets, asterisks, headers.
- Never say "Here is", "Task complete", "I have successfully", "Certainly".
- Max 2-3 sentences total.
- For factual answers, jokes, opinions: speak the actual answer directly. Never summarize what you did.
- For actions (open app, set volume): briefly confirm what was done.
- For creative content (poem, story, essay): say you created it, never show it.
- Never say "I provided", "I explained", "I shared" — just say the thing.
- Always mention number, fact, calculation  and file path. do not remove file path .. 
- menation file path 
    EXAMPLE
        - D:/Learning/tools.py -> D drive Learning folder and tools.py 



EXAMPLES:
User: do you think ai is dangerous?
Result: AI can be dangerous if misused, but it's also one of the most powerful tools humanity has built. Like fire, it depends on who's holding it.

User: open youtube
Result: YouTube is open.

User: can you give me a long motivational story about a boy becoming a man
Result : Done, i write story and save it sir 
User: write a poem about rain
Result: Done, wrote you a poem about rain.
'''),
    ('human', 'User said: {query}\nTask results: {results}')
])


def final_answer_llm(state: KuramaState):
    query   = state['query']
    results = state['results']
    tasks   = state['tasks']

    formatted_results = ""
    for task in tasks:
        result = results.get(task.id, "No result")
        status = "FAILED" if any(w in str(result).lower() for w in ["error", "failed", "exception"]) else "DONE"
        formatted_results += f"[{status}] {task.content}: {result}\n"

    chain  = summarizer_prompt | final_llm | StrOutputParser()
    output = chain.invoke({'query': query, 'results': formatted_results})

    return {'final_response': output}