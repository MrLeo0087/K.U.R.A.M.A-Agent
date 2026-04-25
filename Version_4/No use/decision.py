from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_groq import ChatGroq
from langgraph.graph import START, END, StateGraph
import os

from pydantic import BaseModel, Field
from typing import List, Literal, TypedDict
from dotenv import load_dotenv
load_dotenv()

GROQ_API = os.getenv('GROQ_API_KEY')

llm = ChatGroq(
    model='qwen/qwen3-32b',
    api_key=GROQ_API,
    reasoning_effort='none',
    max_tokens=512         
)

class Decision(TypedDict):
    orginal_query: str
    decision:      str
    question:      list[str]
    final_query:   str
    iteration:     int

class Decision_note(BaseModel):
    need_question: Literal['Yes', 'No']

class Question(BaseModel):
    question: List[str] = Field(
        default_factory=lambda: ["none"],
        description='List of questions. Use ["none"] if no questions needed.'
    )

decision_llm = llm.with_structured_output(Decision_note, method="json_mode")
question_llm = llm.with_structured_output(Question,      method="json_mode")


def decision(state: Decision) -> dict:
    query = state['orginal_query']

    SYSTEM_PROMPT = """Decide if the query needs more info to execute.

Yes → critical info is missing (who, what, which, recipient, file, app, image desc, unclear pronoun) also user query feel incomplete.  
No  → query is complete, greeting, general knowledge, or user said no/nothing/just do it

Return JSON: {{"need_question": "Yes"}} or {{"need_question": "No"}}
"""

    prompt = ChatPromptTemplate([
        ('system', SYSTEM_PROMPT),
        ('human',  '{user_query}')
    ])

    result = (prompt | decision_llm).invoke({'user_query': query}).need_question

    return {
        'decision':  result,
        'iteration': state.get('iteration', 0) + 1
    }

def question_generator(state: Decision) -> dict:
    query = state['orginal_query']

    SYSTEM_PROMPT = (
    "Generate ONLY questions needed to execute the task. Return ['none'] if clear.\n\n"

    "ASK FOR:\n"
    "- image/photo → description/prompt\n"
    "- code → purpose + language\n"
    "- poem/story/essay/report/email → topic or subject\n"
    "- open/close/install app → which app\n"
    "- play song/video → song name or artist\n"
    "- send message/email → recipient + message content\n"
    "- call → who to call\n"
    "- open/edit/delete file → which file\n"
    "- set alarm/reminder → what + when\n"
    "- search/browse → what to search\n"
    "- unclear pronoun (he/she/it/they) → who/what they refer to\n"
    "- translate → target language\n"
    "- turn on/off device/light → which device or room\n\n"

    "NEVER ASK:\n"
    "- greetings, general knowledge, opinions\n"
    "- volume/brightness (assume default)\n"
    "- screenshot, lock, shutdown, restart\n"
    "- famous person by name (infer platform from context)\n\n"

    'Return JSON: {{"question":["q1","q2"]}} or {{"question":["none"]}}'
)

    prompt = ChatPromptTemplate([
        ('system', SYSTEM_PROMPT),
        ('human',  '{user_query}')
    ])

    result = (prompt | question_llm).invoke({'user_query': query}).question

    return {'question': result}


def final_query_generator(state: Decision) -> dict:
    query    = state['orginal_query']
    question = state['question']

    SYSTEM_PROMPT = (
        "Combine the original query and the user's answers into one clear, complete query.\n"
        "Keep the original intent. Output ONLY the final query, nothing else."
    )

    prompt = ChatPromptTemplate([
        ('system', SYSTEM_PROMPT),
        ('human',  'Query: {user_query}\nAnswers: {question_history}')
    ])

    question_history = {}
    real_questions   = [q for q in question if q != "none"]

    for q in real_questions:
        print(f"\n[C.Ai]: {q}")
        answer = input('[C.User]: ')
        question_history[q] = answer

    result = (prompt | llm | StrOutputParser()).invoke({
        'user_query':       query,
        'question_history': question_history
    })

    return {
        'final_query':   result,
        'orginal_query': result  
    }


def final_query(state: Decision) -> dict:
    return {'final_query': state['orginal_query']}

def decision_router(state: Decision) -> str:
    if state['decision'] == 'No' or state.get('iteration', 0) >= 3:
        return 'final_query'
    return 'question_generator'

def question_router(state: Decision) -> str:
    real = [q for q in state['question'] if q != "none"]
    if real:
        return 'final_query_generator'   # has real questions → ask user
    return 'final_query'                 # no questions → just end



graph = StateGraph(Decision)

graph.add_node('decision',              decision)
graph.add_node('question_generator',    question_generator)
graph.add_node('final_query_generator', final_query_generator)
graph.add_node('final_query',           final_query)

graph.add_edge(START, 'decision')

graph.add_conditional_edges(
    'decision',
    decision_router,
    {
        'final_query':        'final_query',
        'question_generator': 'question_generator'
    }
)

graph.add_conditional_edges(
    'question_generator',
    question_router,
    {
        'final_query_generator': 'final_query_generator',
        'final_query':           'final_query'
    }
)

graph.add_edge('final_query_generator', 'decision') 
graph.add_edge('final_query',           END)

app = graph.compile()

if __name__ == "__main__":
    while True:
        user_input = input("Enter your query: ")

        initial_state = {
            'orginal_query': user_input,
            'decision':      '',
            'question':      [],
            'final_query':   '',
            'iteration':     0
        }

        result = app.invoke(initial_state)
        print(result)
        print(f"\n[Final Query]: {result['final_query']}")