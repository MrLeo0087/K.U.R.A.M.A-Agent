import os
from pathlib import Path
from pydantic import BaseModel, Field
from typing import Optional, Union
from langchain_core.tools import tool
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_groq import ChatGroq
from dotenv import load_dotenv  

# Import your custom logic
from interactive_class import (WorkspacePython, 
                               EnvironmentDoctor,
                               ProjectOrganizer,) 

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
        description="Directory path to diagnose. Accepts absolute paths like '/media/disk/My Future/project', relative paths, or '~'. Spaces in path are supported.if path not given then use ."
    )

class OrganizeProjectInput(BaseModel):
    path: str = Field(
        default=".",
        description="Directory path of the project to organize, clean, sync, and check. Accepts relative, absolute paths (e.g. '/media/disk/My Future/project'), or '~'. if path not given then use ."
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
    try:
        doc = EnvironmentDoctor(resolved_path)
        result = doc.run_all()
        # print('result')
        return result

    except Exception as e:
        return e



@tool(args_schema=OrganizeProjectInput)
def organize_and_sync_project(path: str = ".") -> str:
    """Cleans and organize workspace junk, checks AI API connectivity, syncs requirements.txt with exact versions, and initializes missing project config files. It also create requirement.txt file"""
    organizer = ProjectOrganizer(path)

    if not organizer.target_dir.exists():
        return f"Error: Target directory path does not exist: {organizer.target_dir}"

    clean_res = organizer.clean_junk()
    conn_res = organizer.check_connectivity()
    req_res = organizer.sync_requirements()
    files_res = organizer.ensure_workspace_files()

    report = [
        f"=== PROJECT WORKSPACE REPORT: {organizer.target_dir} ===",
        f"[1] CACHE CLEANUP   : {clean_res}",
        f"[2] API CONNECTIVITY:\n{conn_res}",
        f"[3] REQUIREMENTS    : {req_res}",
        f"[4] WORKSPACE SETUP : {files_res}",
        "--------------------------------------------------"
    ]

    return "\n".join(report)




ALL_TOOLS = [
            make_workspace_python, 
             diagnose_workspace_environment,
             organize_and_sync_project,
             ]



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