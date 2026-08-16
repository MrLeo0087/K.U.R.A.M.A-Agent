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
    """Scaffolds and initializes a fresh, structured Python project workspace from scratch.

    Use this tool when you need to start a new project, create directory structures, 
    bootstrap boilerplate files, or set up a clean Python development workspace.

    Capabilities:
    - Creates standard project folder structures.
    - Sets up virtual environment boilerplates and initial configuration files.
    - Prepares clean workspace architecture for python apps.

    When to trigger:
    - User wants to start, create, initialize, or setup a new Python project.
    - User asks to create a repository or project folder at a specific path.

    Example user queries that match this tool:
    - "Initialize a new python project at ~/projects/my_app"
    - "Create a fresh python workspace for a fastAPI backend"
    - "Start a new project folder named demo_service"
    - "Setup project structure at /path/to/dir"
    """
    clean_path = str(path).strip("'\"")
    resolved_path = os.path.abspath(os.path.expanduser(clean_path))

    work = WorkspacePython(resolved_path)
    work.setup()
    return f"Successfully created project at {resolved_path}"


@tool(args_schema=DiagnosticsInput)
def diagnose_workspace_environment(path: str = ".") -> str:
    """Runs a complete system health check, security audit, and environment diagnostic on a Python workspace.

    Use this tool to troubleshoot environment issues, inspect installed dependencies, 
    check CLI tool availability, verify Git configurations, and detect exposed API keys or secrets.

    Capabilities:
    - Environment & Python version audit.
    - CLI tool & binary dependency verification.
    - Secret leak detection & file hygiene check.
    - Git configuration and repo sanity checks.

    When to trigger:
    - User asks why their environment, setup, or python environment is failing or behaving strangely.
    - User wants an audit, health check, doctor report, or troubleshooting scan.

    Example user queries that match this tool:
    - "Diagnose my project environment at ."
    - "Run doctor check on ~/my_project to see if tools are installed"
    - "Check if my python dependencies, git config, and environment are healthy"
    - "Audit this repository for broken packages or leaked API keys"
    - "Why is my python setup not working properly?"
    """
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
    """Cleans up workspace junk files, verifies API key connectivity, syncs requirements.txt with actual environment dependencies, and initializes missing config files.

    Use this tool for project maintenance, file hygiene, dependency synchronization, 
    and ensuring required workspace configurations exist.

    Capabilities:
    - Deletes junk files (`__pycache__`, `.DS_Store`, temporary cache files).
    - Checks internet & AI API connectivity (Groq, OpenAI, Anthropic, etc.).
    - Freezes installed environment dependencies directly into `requirements.txt`.
    - Generates missing default files like `.gitignore`, `.env.example`, or `README.md`.

    When to trigger:
    - User wants to clean, organize, tidy up, or sanitize a project folder.
    - User wants to update or sync `requirements.txt` with currently installed libraries.
    - User wants to test API connectivity or remove temporary python cache files.

    Example user queries that match this tool:
    - "Clean junk files and sync requirements.txt for my project"
    - "Organize this project directory and remove __pycache__ folders"
    - "Check if my API keys are working and generate missing config files"
    - "Tidy up ~/projects/web_app and generate requirements"
    - "Sanitize project directory and sync dependencies"
    """
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
    """Automates Git version control workflow by staging changes, generating semantic commit messages, and pushing to remote repositories (GitHub/GitLab).

    Use this tool to commit code, save changes to Git, push local commits to remote origin, 
    and maintain clean version control hygiene without manually typing git commands.

    Capabilities:
    - Checks `git status` and stages modified / new files.
    - Generates descriptive AI commit messages (or uses custom commit message).
    - Pushes staged commits to origin branch on GitHub/GitLab.

    When to trigger:
    - User asks to git commit, git push, sync code to GitHub, or save changes.
    - User wants to upload code updates or sync local workspace with remote repo.

    Example user queries that match this tool:
    - "Commit and push all my latest changes to GitHub"
    - "Sync git repository with remote origin"
    - "Git commit with message 'fix database query bug' and push"
    - "Save my current work to git and push to master branch"
    - "Upload project changes to my repository"
    """
    clean_path = str(repo_path).strip("'\"")
    resolved_path = os.path.abspath(os.path.expanduser(clean_path))

    assistant = GitAssistant(repo_path=resolved_path)

    if not assistant.is_git_repo():
        return f"Error: Target directory is not a valid Git repository: {assistant.repo_path}"

    result = assistant.auto_commit_and_push(custom_message=custom_message)

    report = [
        f"=== GIT ASSISTANT EXECUTION REPORT: {assistant.repo_path} ===",
        f"STATUS      : {result.get('status', 'upper').upper()}",
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
    """Executes Pytest test suites, captures failing tests, retrieves stack tracebacks, and reads broken source code for AI diagnostics and automated bug fixing.

    Use this tool whenever you need to run unit tests, integration tests, verify code functionality, 
    or debug test failures across a Python codebase.

    Capabilities:
    - Runs pytest on entire directories, specific test files, or matching test function names.
    - Extracts precise stack traces and error logs when tests fail.
    - Returns source code context of failing files so LLM can suggest fixes.

    When to trigger:
    - User wants to test code, run pytest, debug failing tests, or verify fixes.
    - User asks if unit tests pass or wants to inspect code errors.

    Example user queries that match this tool:
    - "Run tests on my project to see if anything is broken"
    - "Execute pytest for tests/test_user.py and suggest a fix if it fails"
    - "Check if my test suite passes"
    - "Run tests matching pattern 'test_auth' in project root"
    - "Debug failing unit tests in ~/projects/my_app"
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
    """Converts a Jupyter Notebook (.ipynb file) into a clean, standalone, executable Python script (.py file).

    Use this tool to extract raw Python code from notebooks, clean up interactive code, 
    strip out shell commands, remove magic commands, and omit non-executable markdown cells.

    Capabilities:
    - Parses `.ipynb` JSON structure into valid Python code.
    - Strips IPython magic commands (`%matplotlib inline`, `%timeit`, etc.).
    - Strips terminal shell executions (`!pip install`, `!bash`, etc.).
    - Formats output into structured, production-ready `.py` scripts.

    When to trigger:
    - User wants to convert, export, turn, or transform a Jupyter Notebook (.ipynb) into a Python script (.py).
    - User wants to refactor notebook code for production deployment.

    Example user queries that match this tool:
    - "Convert model_training.ipynb into a clean python script"
    - "Turn my Jupyter notebook analysis.ipynb into analysis.py"
    - "Export notebook ~/experiments/demo.ipynb to script without magic commands"
    - "Transform ipynb file to python executable code"
    """
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


