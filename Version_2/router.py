from state import KuramaState
from NODE.prompt import router_prompt
from langgraph.graph import StateGraph,START,END
from langchain_groq import ChatGroq
from langchain_core.output_parsers import StrOutputParser

from NODE.general import make_general_node
from NODE.search import make_search_node
from NODE.create import make_create_node


from dotenv import load_dotenv
import os
load_dotenv()

GROQ_API = os.getenv("GROQ_API_KEY")

final_llm = ChatGroq(model='llama-3.1-8b-instant',api_key=GROQ_API)
def final_answer_llm(state: KuramaState):
    query = state['query']
    results = state['results']
    tasks = state['tasks']

    formated_result = ""

    for task in tasks:
        result = results.get(task.id,"No result")
        formated_result += f"Task : {task.content} \nResult : {result} \n\n"

    chain = router_prompt | final_llm | StrOutputParser()

    result = chain.invoke({'query':query,'results':formated_result})

    return {'final_response':result}

node_factories = {
    'general': make_general_node,
    'search': make_search_node,
    'create': make_create_node,
    # 'auto': make_auto_node
}

def build_graph(tasks:list):
    graph = StateGraph(KuramaState)

    for task in tasks:
        node_name = f"task_{task.id}"
        factory = node_factories[task.tag]
        graph.add_node(node_name, factory(task))

    graph.add_node("final_answer_llm",final_answer_llm)
    depend_set = set()
    for task in tasks:
        if task.depends_on:
            for id in task.depends_on:
                depend_set.add(id)

    # print(f"DEPEND SET : {depend_set}")

    for task in tasks:
        node_name = f"task_{task.id}"
        if not task.depends_on:
            graph.add_edge(START,node_name)
            # print(f"START -> {node_name}")

        else:
            for parent_id in task.depends_on:
                graph.add_edge(f'task_{parent_id}',node_name)
                # print(f"task_{parent_id} -> {node_name}")
    for task in tasks:
        if task.id not in depend_set:
            graph.add_edge(f"task_{task.id}",'final_answer_llm')
            # print(f"task_{task.id} -> final_answer_llm")

    graph.add_edge('final_answer_llm',END)


    return graph.compile()



if __name__ =='__main__' :
    app = build_graph("generate image of person and save it on file and also open youtube and search for nepali song then write letter and send it on mail")
    print(app.get_graph().draw_mermaid())
    app.get_graph().print_ascii()





    

    




