from voice import kurama

kurama.speak("System Inilization")
from router import build_graph
from query_process.decision_node import tasks_list
import asyncio

from NODE.state import KuramaState

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
            await kurama.speak(result['final_response'])

        asyncio.run(run_jarvis())