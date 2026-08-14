import os
from pathlib import Path
from pydantic import BaseModel, Field
from langchain_core.tools import tool
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_groq import ChatGroq
from dotenv import load_dotenv  

# Import your custom logic
from interactive_class import WorkspacePython, EnvironmentDoctor

load_dotenv()


# --------------------------------------------------
# 1. DEFINE EXPLICIT SCHEMAS (Fixes Groq 400 Error)
# --------------------------------------------------

class WorkspaceInput(BaseModel):
    path: str = Field(
        ..., 
        description="Target directory path for the project. e.g. '~/newproject' or '/path/to/dir'"
    )

class DiagnosticsInput(BaseModel):
    path: str = Field(
        default=".", 
        description="Directory path to diagnose. Accepts absolute paths like '/media/disk/My Future/project', relative paths, or '~'. Spaces in path are supported."
    )


# --------------------------------------------------
# 2. DEFINE TOOLS WITH ARGS_SCHEMA
# --------------------------------------------------

@tool(args_schema=WorkspaceInput)
def make_workspace_python(path: str) -> str:
    """Initializes a new Python project workspace."""
    clean_path = path.strip("'\"")
    resolved_path = os.path.abspath(os.path.expanduser(clean_path))

    work = WorkspacePython(resolved_path)
    work.setup()
    return f"Successfully created project at {resolved_path}"


@tool(args_schema=DiagnosticsInput)
def diagnose_workspace_environment(path: str = ".") -> str:
    """Runs diagnostics on Python environment, CLI tools, Git config, secrets, dependencies, and file hygiene."""
    clean_path = path.strip("'\"")
    resolved_path = os.path.abspath(os.path.expanduser(clean_path))

    if not os.path.exists(resolved_path):
        return f"Error: Target directory path does not exist: {resolved_path}"

    doc = EnvironmentDoctor(resolved_path)

    sys_res = doc.check_system_and_python()
    tools_res = doc.check_system_tools()
    git_res = doc.check_git_status()
    secrets_res = doc.check_secrets_and_env()
    deps_res = doc.check_dependencies() 
    hygiene_res = doc.check_repo_hygiene()

    lines = [
        f"--- WORKSPACE DIAGNOSTICS: {resolved_path} ---",
        f"[1] SYSTEM RUNTIME: Python {sys_res['python_version']} | Venv Active: {sys_res['in_venv']} | Disk Free: {sys_res['free_disk_gb']} GB",
        f"[2] SYSTEM TOOLS  : Installed: {', '.join(tools_res['installed'])} | Missing: {', '.join(tools_res['missing']) if tools_res['missing'] else 'None'}",
        f"[3] GIT STATUS    : Repo Init: {git_res['initialized']} | Identity: {git_res.get('user_name')} <{git_res.get('user_email')}> | Branch: {git_res.get('branch')} | Dirty Work Tree: {git_res.get('is_dirty')}",
        f"[4] SECRETS & ENV : .env Exists: {secrets_res['env_present']} | Safe in Gitignore: {secrets_res['is_ignored']} | Keys Found: {', '.join(secrets_res['keys']) if secrets_res['keys'] else 'None'}",
        f"[5] DEPENDENCIES  : Source: {deps_res['source']} | Installed: {len(deps_res['installed'])} | Missing: {', '.join(deps_res['missing']) if deps_res['missing'] else 'None'}",
        f"[6] REPO HYGIENE  : Large Files (>50MB): {len(hygiene_res['large_files'])} | Cache Folders: {', '.join(hygiene_res['cache_folders']) if hygiene_res['cache_folders'] else 'None'}",
        "--------------------------------------------------",
        f"OVERALL STATUS     : {'ALL SYSTEMS GO' if all(passed for _, passed in doc.summary_status) else 'ACTION REQUIRED'}"
    ]

    return "\n".join(lines)


ALL_TOOLS = [make_workspace_python, diagnose_workspace_environment]


# --------------------------------------------------
# 3. INTERACTIVE AGENT WITH SYSTEM PROMPT
# --------------------------------------------------

class InteractiveAgent:

    def __init__(self):
        self.tools_map = {t.name: t for t in ALL_TOOLS}
        self.llm = ChatGroq(model="llama-3.1-8b-instant", temperature=0)
        
        # System message instructs model how to handle path strings with spaces
        self.system_message = SystemMessage(
            content="You are a helpful assistant with tool access. "
                    "When passing file system paths to tools, pass the unquoted, exact raw path string into the JSON argument."
        )

    def process_command(self, user_prompt: str):
        print(f"\nUser: '{user_prompt}'")
        try:
            llm_with_tools = self.llm.bind_tools(ALL_TOOLS)
            
            # Send both system and user message
            messages = [self.system_message, HumanMessage(content=user_prompt)]
            response = llm_with_tools.invoke(messages)

            if response.tool_calls:
                for tool_call in response.tool_calls:
                    tool_name = tool_call["name"]
                    args = tool_call["args"]

                    print(f"-> Executing [{tool_name}] with args: {args}")

                    if tool_name in self.tools_map:
                        result = self.tools_map[tool_name].invoke(args)
                        print(f"-> Result:\n{result}")
                        return "Diagnostics completed successfully."
                    else:
                        print(f"-> Error: Tool '{tool_name}' not registered.")
            else:
                print(f"LLM Response: {response.content}")
                return response.content
        except Exception as e:
            print(f"-> Execution failed: {e}")


if __name__ == '__main__':
    agent = InteractiveAgent()
    while True:
        user_input = input('\nEnter your command : ')
        if user_input.strip().lower() in ['exit', 'quit']:
            break

        answer = agent.process_command(user_input)
        print(f'Jarvis : {answer}') 
        print('-'*50)