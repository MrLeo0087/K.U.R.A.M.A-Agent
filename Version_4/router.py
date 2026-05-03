import os
import sys

# --- PLACE CLEANUP CODE HERE (Top of the file) ---
os.environ["HF_HUB_DISABLE_IMPLICIT_TOKEN"] = "1"
from transformers.utils import logging as transformers_logging
from huggingface_hub import logging as hub_logging
transformers_logging.set_verbosity_error()
hub_logging.set_verbosity_error()

import warnings
warnings.filterwarnings("ignore")

from query_process.decision_node import tasks_list
from langgraph.graph import START,END,StateGraph
from NODE.state import KuramaState
from NODE.final_answer import final_answer_llm
from NODE.search_node import make_search_node
from NODE.create_node import make_create_node
from NODE.general_node import make_general_node
import asyncio
from AUTO_NODE.auto_node import ToolManager
from AUTO_NODE.auto_node import make_auto_node, init_manager,manager


node_factories = {
    'general': make_general_node,
    'search': make_search_node,
    'create': make_create_node,
    'auto': make_auto_node
}

def build_graph(tasks: list,tool_manager: ToolManager):
    if not tasks:
        print("❌ No tasks generated. Check your decision_node.")
        return None

    try:
        graph = StateGraph(KuramaState)

        # 1. Add Nodes
        for task in tasks:
            node_name = f"task_{task.id}"
            if task.tag not in node_factories:
                raise ValueError(f"Unknown tag '{task.tag}' in task {task.id}")
            
            factory = node_factories.get(task.tag)
            
            # --- THE FIX ---
            if task.tag == 'auto':
                # Pass both task and manager to the auto factory
                node_func = factory(task, tool_manager)
            else:
                # Other nodes (general, search, create) only take the task
                node_func = factory(task)
            
            graph.add_node(node_name, node_func)

        graph.add_node("final_answer_llm", final_answer_llm)

        # 2. Build Dependency Set
        depend_set = set()
        for task in tasks:
            if task.depends_on:
                for parent_id in task.depends_on:
                    depend_set.add(parent_id)

        # 3. Add Edges from START and between tasks
        for task in tasks:
            node_name = f"task_{task.id}"
            if not task.depends_on:
                graph.add_edge(START, node_name)
            else:
                for parent_id in task.depends_on:
                    graph.add_edge(f'task_{parent_id}', node_name)

        # 4. Connect leaf nodes to final answer
        for task in tasks:
            if task.id not in depend_set:
                graph.add_edge(f"task_{task.id}", 'final_answer_llm')

        graph.add_edge('final_answer_llm', END)

        return graph.compile()

    except Exception as e:
        # Added 'f' for f-string so you can actually see the error
        print(f"❌ Graph build failed: {e}") 
        return None # Explicitly return None to handle in kurama.py
    
if __name__ == '__main__':
    # Initialize the global manager once
    # This keeps your MCP servers and Vector Index alive
    async def initialize_and_run():
        print("Starting K.U.R.A.M.A...")
        # Assuming init_manager() sets up your global manager instance
        await init_manager() 
        
        while True:
            user_query = input("[USER]: ")
            if user_query.lower() in ["exit", "quit"]:
                break

            tasks = tasks_list(user_query)
            # PASS THE MANAGER HERE
            workflow = build_graph(tasks, manager) 

            if workflow:
                initial_state = {
                    "query": user_query,
                    "tasks": tasks,
                    "results": {},
                    "merge_results": "",
                    "final_response": ""
                }
                
                result = await workflow.ainvoke(initial_state)
                print(f"[AI]: {result['final_response']}")

    # Use a single asyncio.run for the entire loop
    asyncio.run(initialize_and_run())