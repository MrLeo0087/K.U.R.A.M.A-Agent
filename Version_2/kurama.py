from router import build_graph
from decision import decision_node

while True:
    user_query = input('\n[USER]: ')
    tasks = decision_node(user_query)
    print(tasks)

    print('[KURAMA]: ',end="")
    if user_query.lower() in ['end','bye','q','quit','goodbye']:
        print('Good Bye !')
        break


    initial_state = {'query': user_query, 'tasks': tasks, 'results': {}, 'final_response':  None}
    workflow = build_graph(tasks)
    result = workflow.invoke(initial_state)
    print(result['final_response'])