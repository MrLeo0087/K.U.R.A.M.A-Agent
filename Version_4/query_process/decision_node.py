from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_groq import ChatGroq
from typing import Literal, List
from pydantic import BaseModel, Field
from dotenv import load_dotenv
from query_process.query_preprocess import decision_node
import os
from voice import sync_speak
from mic import listen_controlled

load_dotenv()

GROQ_KEY = os.getenv('GROQ_API_KEY')

llm = ChatGroq(
    model='llama-3.3-70b-versatile',
    api_key=GROQ_KEY,
    max_tokens=512
)
llm_2 = ChatGroq(
    model='meta-llama/llama-4-scout-17b-16e-instruct',
    api_key=GROQ_KEY
)

# ── Models ──────────────────────────────────────────────────────────────────

class Decision(BaseModel):
    need_question: Literal['Yes', 'No']

class Questions(BaseModel):
    question: List[str] = Field(
        default_factory=lambda: ["none"],
        description='List of questions. Use ["none"] if nothing needed.'
    )

# ── Prompts ──────────────────────────────────────────────────────────────────

DECISION_PROMPT = """Decide if the query needs more info to execute.

Yes → critical info missing: app name, recipient, file, image desc, song, unclear pronoun, incomplete intent, topic or subject not clear of peom, story or code

No  → greeting,opinion, or all info present, setting open

#RULE
- if you feel user query is not complete to execute and it need more context then yes otherwise no
- if user ask for time then no
- if user ask for weather then look for location. if location is given then no if not then yes
- if user share it feeling then also analysis it. if there need to cross question then yes
- if user ask for poem, story, code or other content generate then look for subject or topic. if missing then yes
- if user ask for adjust volume, brightness or app, Never ask which device. it always this laptop. 
- if user ask for open file and file name and location provide then no
Return JSON: {{"need_question": "Yes"}} or {{"need_question": "No"}}"""


QUESTION_PROMPT = """You are a warm, helpful AI assistant. Ask ONLY what is truly missing to complete the task.

ASK when missing:
- app → which app (SKIP if app name already mentioned)
- image/photo → what it should look like
- code → purpose + language
- creative (poem/story/essay/email) → topic or subject  
- song/video → name or artist
- send/call → who + what
- file → which one and where
- alarm/reminder → what + when
- pronoun (he/she/it/they) → who/what
- translate → to which language
- device/light → which one
- notifacation → which app or website notifaction
- user feeling or thinking → what user feel ask very warmly

RULE
- if query look clear and no question then then return {{"question": ["none"]}}
- if you feel query is complete then return none
- generate very humble and humanize style question
- Do not repeat user query 
- Do not generate unnecessary query. just generate query that matter
- if any task depend on other task then adjust question according to it.


Task                                        Look for
poem, story essay writing                   subject and topic
email, mail send                            email address
send message                                platform ( can be facebook, whatsapp, instagram)


NEVER ASK:
- greetings, knowledge, opinions
- volume, brightness, screenshot, lock, shutdown
- famous person by name

STYLE — vary naturally, sound human and warm:
- "Mind telling me which app to open?"
- "What should the image look like — any details?"
- "Who's the lucky recipient?"
- "Could you share the topic for the essay?"
- "Which song are we going with?"

Return JSON: {{"question": ["q1", "q2"]}} or {{"question": ["none"]}}"""


MERGE_PROMPT = """Combine the original query and answers into one clean, complete final query.
Silently fix any spelling mistakes. Keep original intent. Output ONLY the final query. do not ask any question. just refine
query for better result for llm. if multiple task depend with eachother then manage it as well

RULE
- do not give answer of user query 
- just refine query and make it more understable. do not change meaning and context of query of user
- give direct query

WRONG -> Which app should I open for you? For example, Chrome.
RIGHT -> Open chrome

WRONG -> Who is "he" referring to? (Context: "messi")
RIGHT -> who is messi
"""

# ── Chains ───────────────────────────────────────────────────────────────────

decision_prompt = ChatPromptTemplate([
    ('system', DECISION_PROMPT),
    ('human', 'query: {user_query}')
])

question_prompt = ChatPromptTemplate([
    ('system', QUESTION_PROMPT),
    ('human', 'query: {user_query}')
])

merge_prompt = ChatPromptTemplate([
    ('system', MERGE_PROMPT),
    ('human', 'query: {user_query}\nanswers: {question_history}')
])

decision_llm  = llm.with_structured_output(Decision,  method='json_mode')
question_llm  = llm_2.with_structured_output(Questions, method='json_mode')

decision_chain = decision_prompt | decision_llm
question_chain = question_prompt | question_llm
merge_chain    = merge_prompt    | llm | StrOutputParser()

# ── Main Loop ────────────────────────────────────────────────────────────────
def tasks_list(query: str):
    user_query=query
    question_history = {}
    decision = decision_chain.invoke({'user_query': query}).need_question

    if decision == 'No':
            print(f'\n[Final Query]: {user_query}')
            tasks = decision_node(user_query)
            print(f'[Tasks]: {tasks}')
            return tasks

    else:
            result = question_chain.invoke({
                'user_query': user_query
            }).question

            real_questions = [q for q in result if q != 'none']

            if not real_questions:
                print(f'\n[Final Query]: {user_query}')

            else:
                for q in real_questions:
                    print(f'[C.Ai]: {q}')
                    sync_speak(q)
                    # answer = input('[C.User]: ')
                    answer = listen_controlled()
                    # answer = input("[C.User]: ")
                    print(f'[C.User]: {answer}')
                    question_history[q] = answer

                user_query = merge_chain.invoke({
                    'user_query': user_query,
                    'question_history': question_history
                })
                print(f'[Refined Query]: {user_query}')
                tasks = decision_node(user_query)
                # print(f'[Tasks]: {tasks}')
                return tasks
     
if __name__=='__main__':
    while True:
        user_query = input('\n[USER]: ')
        if user_query == 'q':
            break

        question_history = {}
        decision = decision_chain.invoke({'user_query': user_query}).need_question

        if decision == 'No':
                print(f'\n[Final Query]: {user_query}')
                tasks = decision_node(user_query)
                print(f'[Tasks]: {tasks}')

        else:
                result = question_chain.invoke({
                    'user_query': user_query
                }).question

                real_questions = [q for q in result if q != 'none']

                if not real_questions:
                    break

                for q in real_questions:
                    print(f'[C.Ai]: {q}')
                    answer = input('[C.User]: ')
                    question_history[q] = answer

                user_query = merge_chain.invoke({
                    'user_query': user_query,
                    'question_history': question_history
                })
                print(f'[Refined Query]: {user_query}')
                tasks = decision_node(user_query)
                print(f'[Tasks]: {tasks}')