from interactive_class import WorkspacePython

from langchain_core.tools import tool
from langchain_groq import ChatGroq
from dotenv import load_dotenv  
import os
load_dotenv()

@tool
def make_workspace_python(path: str) -> str:
    """Initializes a new Python project workspace.

    Args:
        path (str): The target directory path. Always use the tilde '~' shortcut for home directory paths (e.g., '~/newproject' or '~/projects/my_app').
    """
    # os.path.expanduser converts '~/newproject' into '/home/leo/newproject'
    resolved_path = os.path.abspath(os.path.expanduser(path))

    work = WorkspacePython(resolved_path)
    work.setup()
    return f"Successfully created project at {resolved_path}"


ALL_TOOLS = [make_workspace_python]

class InteractiveAgent:

    def __init__(self):
        self.tools_map = {tool.name: tool for tool in ALL_TOOLS}
        self.llm = ChatGroq(model="llama-3.1-8b-instant", temperature=0)

    def process_command(self, user_prompt: str):
        print(f"\nUser: '{user_prompt}'")
        try:

            llm_with_tools = self.llm.bind_tools(ALL_TOOLS)
            response = llm_with_tools.invoke(user_prompt)

            if response.tool_calls:
                for tool_call in response.tool_calls:
                    tool_name = tool_call["name"]
                    args = tool_call["args"]

                    print(f"-> Executing [{tool_name}] with args: {args}")

                    if tool_name in self.tools_map:
                        result = self.tools_map[tool_name].invoke(args)
                        print(f"-> Result: {result}")
                        return response.content
                    else:
                        print(f"-> Error: Tool '{tool_name}' not registered.")
            else:
                print(f"LLM Response: {response.content}")
                return response.content
        except Exception as e:
            print(f"-> Execution failed: {e}")


if __name__ == '__main__':
    while True:
        user_input = input('Enter your command : ')

        jarvis = InteractiveAgent()

        answer = jarvis.process_command(user_input)

        print(f'Jarvis : {answer}') 
        print('-'*50)