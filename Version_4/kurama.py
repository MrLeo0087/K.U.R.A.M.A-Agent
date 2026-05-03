from voice import kurama, sync_speak
print('System initialization sir .....')
sync_speak("System initialization sir!")

print('Checking system .... ')
sync_speak('Checking system .. please wait')
from mic import listen_controlled
from router import build_graph
from AUTO_NODE.auto_node import manager,init_manager

from query_process.decision_node import tasks_list
import asyncio
from NODE.state import KuramaState
print('System Ready sir!')
sync_speak('System Ready sir!')

async def run_jarvis():
    await init_manager() 
    while True:
        
            # user_query = input("[USER]: ")
            user_query = listen_controlled()
            # user_query = input("[USER]: ")
            print(f'[USER]: {user_query}')
            if user_query.lower().strip() in ["exit", "quit"]:
                print("Shutting down...")
                sync_speak("Shutting down. Goodbye sir.")
                break
            if user_query.strip():
                tasks = tasks_list(f'{user_query}')
                workflow = build_graph(tasks, manager) 
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
                

                result = await workflow.ainvoke(initial_state)
                print("[AI]: ", end="", flush=True)
                print(result['final_response'])
                await kurama.speak(result['final_response'])

asyncio.run(run_jarvis())