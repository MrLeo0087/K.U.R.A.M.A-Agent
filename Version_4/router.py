from query_process.decision_node import tasks_list
from langgraph.graph import START,END,StateGraph
from NODE.state import KuramaState
from NODE.final_answer import final_answer_llm
from NODE.search_node import make_search_node
from NODE.create_node import make_create_node
from NODE.general_node import make_general_node
import asyncio
from AUTO_NODE.auto_node import make_auto_node

node_factories = {
    'general': make_general_node,
    'search': make_search_node,
    'create': make_create_node,
    'auto': make_auto_node
}

def build_graph(tasks:list):
    try:
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

        for task in tasks:
            node_name = f"task_{task.id}"
            if not task.depends_on:
                graph.add_edge(START,node_name)

            else:
                for parent_id in task.depends_on:
                    graph.add_edge(f'task_{parent_id}',node_name)

        for task in tasks:
            if task.id not in depend_set:
                graph.add_edge(f"task_{task.id}",'final_answer_llm')

        graph.add_edge('final_answer_llm',END)


        return graph.compile()

    except Exception as e:
        print("Graph build failed: {e}")

if __name__ =='__main__' :
    while True:
        user_query = input("[USER]: ")
        if user_query.lower() in ["exit", "quit"]:
            break

        tasks = tasks_list(user_query)
        workflow = build_graph(tasks)
        initial_state = KuramaState(
                query          = user_query,
                tasks          = tasks,
                results        = {},
                merge_results  = "",
                final_response = ""
            )
        
        # FIXED: Correct indentation and calling via asyncio.run
        async def run_jarvis():
            print(f"DEBUG: workflow type is {type(workflow)}")
            result = await workflow.ainvoke(initial_state)
            print("[AI]: ", end="", flush=True)
            print(result['final_response'])

        asyncio.run(run_jarvis())