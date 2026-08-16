import os
from pathlib import Path
from typing import Optional
from pydantic import BaseModel, Field
from langchain_core.tools import tool
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_groq import ChatGroq
from dotenv import load_dotenv  

# Import custom logic
from interactive_class import (
    WorkspacePython, 
    EnvironmentDoctor,
    ProjectOrganizer,
    GitAssistant,
    TestRunnerController,
    NotebookScriptConverter,
) 

load_dotenv()

# --------------------------------------------------
# 1. SCHEMAS
# --------------------------------------------------

class WorkspaceInput(BaseModel):
    path: str = Field(
        ..., 
        description="Target directory path for the project. e.g. '~/newproject' or '/path/to/dir'"
    )

class DiagnosticsInput(BaseModel):
    path: str = Field(
        default=".", 
        description="Directory path to diagnose. Accepts absolute paths, relative paths, or '~'."
    )

class OrganizeProjectInput(BaseModel):
    path: str = Field(
        default=".",
        description="Directory path of the project to organize, clean, sync, and check."
    )

class GitAssistantInput(BaseModel):
    repo_path: str = Field(
        default=".",
        description="Path to the local git repository directory."
    )
    custom_message: Optional[str] = Field(
        default=None,
        description="Optional custom commit message."
    )

class TestRunnerInput(BaseModel):
    project_path: str = Field(
        default=".",
        description="Path to the directory containing tests or the project root.",
    )
    test_file: Optional[str] = Field(
        default=None,
        description="Optional specific test file path (e.g., 'tests/test_app.py').",
    )
    test_pattern: Optional[str] = Field(
        default=None,
        description="Optional pattern/keyword to match test names (e.g., 'test_user_name').",
    )

# --------------------------------------------------
# 2. TOOLS WITH SAFE PATH RESOLUTION
# --------------------------------------------------

@tool(args_schema=WorkspaceInput)
def make_workspace_python(path: str) -> str:
    """Initializes a new Python project workspace."""
    clean_path = str(path).strip("'\"")
    resolved_path = os.path.abspath(os.path.expanduser(clean_path))

    work = WorkspacePython(resolved_path)
    work.setup()
    return f"Successfully created project at {resolved_path}"


@tool(args_schema=DiagnosticsInput)
def diagnose_workspace_environment(path: str = ".") -> str:
    """Runs diagnostics on Python environment, CLI tools, Git config, secrets, dependencies, and file hygiene."""
    clean_path = str(path).strip("'\"")
    resolved_path = os.path.abspath(os.path.expanduser(clean_path))

    if not os.path.exists(resolved_path):
        return f"Error: Target directory path does not exist: {resolved_path}"
    try:
        doc = EnvironmentDoctor(resolved_path)
        return doc.run_all()
    except Exception as e:
        return f"Diagnostic Error: {str(e)}"


@tool(args_schema=OrganizeProjectInput)
def organize_and_sync_project(path: str = ".") -> str:
    """Cleans and organizes workspace junk, checks AI API connectivity, syncs requirements.txt with exact versions, and initializes missing project config files."""
    
    # FIX: Explicitly cast 'path' to string first so .strip() works regardless of input type!
    path_str = str(path).strip("'\"")
    resolved_path = Path(os.path.abspath(os.path.expanduser(path_str)))

    organizer = ProjectOrganizer(resolved_path)

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


@tool(args_schema=GitAssistantInput)
def git_assistant_auto_commit_and_push(repo_path: str = ".", custom_message: Optional[str] = None) -> str:
    """Automates git commit hygiene and synchronization. Stages changes, generates commit messages, and pushes to remote GitHub repository."""
    clean_path = str(repo_path).strip("'\"")
    resolved_path = os.path.abspath(os.path.expanduser(clean_path))

    assistant = GitAssistant(repo_path=resolved_path)

    if not assistant.is_git_repo():
        return f"Error: Target directory is not a valid Git repository: {assistant.repo_path}"

    result = assistant.auto_commit_and_push(custom_message=custom_message)

    report = [
        f"=== GIT ASSISTANT EXECUTION REPORT: {assistant.repo_path} ===",
        f"STATUS      : {result.get('status', 'unknown').upper()}",
        f"MODE USED   : {result.get('diff_mode_used', 'N/A')}",
        f"COMMIT MSG  : {result.get('commit_message', 'N/A')}",
        f"DETAILS     : {result.get('message', '')}",
        "--------------------------------------------------"
    ]

    return "\n".join(report)

@tool(args_schema=TestRunnerInput)
def run_tests_and_suggest_fix(
    project_path: str = ".",
    test_file: Optional[str] = None,
    test_pattern: Optional[str] = None,
) -> str:
    """Runs automated Pytest test suites.

    If a test fails, reads the broken file and returns the error traceback so
    Jarvis can diagnose and propose a code fix.
    """
    controller = TestRunnerController(project_dir=project_path)
    result = controller.run_pytest_and_diagnose(
        test_path=test_file, test_pattern=test_pattern
    )

    if result["status"] == "success":
        return f"✅ SUCCESS:\n{result['summary']}\n{result['output']}"

    elif result["status"] == "failed":
        response_lines = [
            f"❌ TEST FAILURE DETECTED:",
            f"Summary: {result['summary']}",
            f"\n--- TRACEBACK ---",
            result["traceback"],
        ]

        if result.get("failing_file") and result.get("source_code"):
            response_lines.extend(
                [
                    f"\n--- FAILING FILE: {result['failing_file']} ---",
                    result["source_code"],
                    f"\n[INSTRUCTION FOR LLM: Analyze the failure above and suggest the exact fix for {result['failing_file']}]",
                ]
            )

        return "\n".join(response_lines)

    else:
        return (
            f"⚠️ {result['summary']}\nDetails: {result.get('output', 'None')}"
        )

@tool
def convert_notebook_to_script(
    notebook_path: str, output_path: Optional[str] = None
) -> str:
    """Converts a Jupyter Notebook (.ipynb) into a clean, runnable Python script (.py).

    Removes markdown cells, strips out shell commands (!) and magic commands (%),
    and structures the output cleanly.

    Args:
        notebook_path: Path to the input .ipynb file.
        output_path: Optional output path for the .py file.
    """
    # Instantiate the class and execute the process
    converter = NotebookScriptConverter(
        notebook_path=notebook_path, output_path=output_path
    )
    result = converter.convert()

    return result["message"]

INTERACTIVE_TOOLS = [
    make_workspace_python, 
    diagnose_workspace_environment,
    organize_and_sync_project,
    git_assistant_auto_commit_and_push,
    run_tests_and_suggest_fix,
    convert_notebook_to_script
]


# --------------------------------------------------
# 3. INTERACTIVE AGENT
# --------------------------------------------------

class InteractiveAgent:

    def __init__(self):
        self.tools_map = {t.name: t for t in INTERACTIVE_TOOLS}
        self.llm = ChatGroq(model="llama-3.3-70b-versatile", temperature=0)
        
        self.system_message = SystemMessage(
            content=(
                "You are Jarvis, an expert coding assistant.\n"
                "When a user asks to clean, organize, diagnose, or git push a project path, "
                "select the appropriate tool and pass the absolute directory path string in the JSON payload."
            )
        )

    def process_command(self, user_prompt: str):
        print(f"\nUser: '{user_prompt}'")
        try:
            llm_with_tools = self.llm.bind_tools(INTERACTIVE_TOOLS)
            
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
                        return "Command executed successfully."
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


