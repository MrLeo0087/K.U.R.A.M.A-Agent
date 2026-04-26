from voice import kurama, sync_speak
print('System initialization sir .....')
sync_speak("System initialization sir!")

print('Checking system .... ')
sync_speak('Checking system .. please wait')
from mic import listen_controlled
from router import build_graph
from query_process.decision_node import tasks_list
import asyncio
from NODE.state import KuramaState
print('System Ready sir!')
sync_speak('System Ready sir!')

while True:
        # user_query = input("[USER]: ")

        user_query = listen_controlled()
        print(f'[USER]: {user_query}')
        if user_query.lower() in ["exit", "quit"]:
            break
        if user_query.strip():
            tasks = tasks_list(user_query)
            workflow = build_graph(tasks)
            if workflow is None:
                sync_speak("Could not build the graph for this query. Try again.")
                continue
            initial_state = KuramaState(
                    query          = user_query,
                    tasks          = tasks,
                    results        = {},
                    merge_results  = "",
                    final_response = ""
                )
            
            # FIXED: Correct indentation and calling via asyncio.run
            async def run_jarvis():
                # print(f"DEBUG: workflow type is {type(workflow)}")
                result = await workflow.ainvoke(initial_state)
                print("[AI]: ", end="", flush=True)
                print(result['final_response'])
                await kurama.speak(result['final_response'])

            asyncio.run(run_jarvis())