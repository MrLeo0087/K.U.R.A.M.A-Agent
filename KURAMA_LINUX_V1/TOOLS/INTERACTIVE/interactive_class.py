# PYTHON ENVIRMENT CREATE
import subprocess
import sys
import os

from templete import gitignore,readme,requirement
class WorkspacePython:
    def __init__(self,folder):
        self.folder_path = folder
        os.makedirs(self.folder_path, exist_ok = True )

    def setup(self):
        print('Creating virtual enviroment in ',self.folder_path)
        self.venv()

        print('Setup README, Requirment and gitignore file ..... ')
        self.need_file_create()

        print('Folder setup ....')
        self.folder_setup()

        print('Git initilization .... ')
        self.init_git_repo()

        print('Workspace complete. All file and folder succesfully created ! ')


    def venv(self):
        '''This create virtual enviroment'''
        venv_path = os.path.abspath(os.path.join(self.folder_path,'venv'))
        command_venv = [sys.executable,'-m','venv',venv_path]

        try:
            if not os.path.exists(venv_path):
                result = subprocess.run(
                    command_venv,
                    capture_output=True,
                    text=True
                )

                print('Virtual enviroment create successfully!')
                print(f"Activate it using:\nsource venv/bin/activate")

            else:
                print('Already venv file exist')


        except subprocess.CalledProcessError as e:
            print(f"Failed to create virtual environment.\nError:\n{e.stderr}")

    def need_file_create(self):
        #create requirement.txt
        
        file_list = ['requirement.txt','README.md','.gitignore']

        for i in file_list:
            path = os.path.join(self.folder_path,i)
            with open(path,'w') as f:
                if i == 'requirement.txt':
                    f.write(requirement)

                elif i == '.gitignore':
                    f.write(gitignore)

                elif i == 'README.md':
                    f.write(readme)

    def folder_setup(self):
        folder_name = ['src','test','bin']

        for i in folder_name:
            path = os.path.join(self.folder_path,i)

            os.makedirs(path,exist_ok=True)

            if i == 'src':
                with open(os.path.join(path,'main.py'),'w') as f:
                    f.write('# write your code here')

                with open(os.path.join(path,'code.ipynb'),'w') as f:
                                    f.write('# write your code here')

            elif i == 'test':
                with open(os.path.join(path,'test.py'),'w') as f:
                    f.write('# write your test code here')


    def init_git_repo(self):
        # 1. Expand user shortcuts (like ~) and resolve relative paths
        self.folder_path = os.path.abspath(os.path.expanduser(self.folder_path))

        # 2. Create the target directory if it doesn't already exist
        os.makedirs(self.folder_path, exist_ok=True)

        # 3. Check if .git folder already exists
        git_dir = os.path.join(self.folder_path, ".git")
        if os.path.exists(git_dir):
            print(f"⚠️ Git repository already initialized at: {self.folder_path}")
            return

        # 4. Run `git init` inside the specific folder
        try:
            # Option A: Pass the target directory path directly to git init
            result = subprocess.run(
                ["git", "init", self.folder_path],
                check=True,
                capture_output=True,
                text=True,
            )

            print(f"✅ Successfully initialized Git repository at: {self.folder_path}")

            choice = (
                input("Which workspace do you want to choose [personal/work]: ")
                .strip()
                .lower()
            )

            # 3. Define account mappings
            if choice == "personal":
                email = "satorugojo0087@gmail.com"
                name = "Personal Account"  # Change to your preferred display name
            elif choice == "work":
                email = "imleo0087@gmail.com"
                name = "Darshan Chaulagain"  # Your work display name
            else:
                print("⚠️ Invalid choice! Defaulting to work account.")
                email = "imleo0087@gmail.com"
                name = "Darshan Chaulagain"

            # 4. Set local git user.email
            subprocess.run(
                ["git", "config", "user.email", email],
                cwd=self.folder_path,
                check=True,
            )

            # 5. Set local git user.name
            subprocess.run(
                ["git", "config", "user.name", name],
                cwd=self.folder_path,
                check=True,
            )

            print(f"👤 Set Git identity for this repo to: {name} <{email}>")

        except subprocess.CalledProcessError as e:
            print(
                f"❌ Failed to initialize Git repository.\nError: {e.stderr.strip()}"
            )
        except FileNotFoundError:
            print(
                "❌ Git is not installed on your system. Run 'sudo apt install git' on Ubuntu."
            )



# FOr doctor of code
"""
Environment & Workspace Diagnostic Tool
Analyzes system, python dependencies, git configuration, secrets, and repo hygiene.
"""

import ast
import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path


class EnvironmentDoctor:
    """Consolidated workspace diagnostic engine."""

    MIN_PYTHON_VERSION = (3, 9)
    MAX_FILE_SIZE_MB = 50.0

    STDLIB_MODULES = set(sys.builtin_module_names) | {
        "ast", "argparse", "asyncio", "collections", "copy", "csv", "datetime",
        "functools", "importlib", "io", "itertools", "json", "logging", "math",
        "multiprocessing", "os", "pathlib", "random", "re", "shutil", "socket",
        "string", "subprocess", "sys", "threading", "time", "typing", "unittest"
    }

    PACKAGE_MAPPINGS = {
        "bs4": "beautifulsoup4",
        "sklearn": "scikit-learn",
        "PIL": "pillow",
        "cv2": "opencv-python",
        "yaml": "pyyaml",
        "pyyaml": "yaml",
        "dotenv": "python-dotenv",
        "fitz": "pymupdf",
        "docx": "python-docx"
    }

    def __init__(self, target_dir=None):
        self.target_dir = Path(target_dir).resolve() if target_dir else Path.cwd()
        self.summary_status = []

    def log_header(self, title):
        print(f"\n--- {title} ---")

    def check_system_and_python(self):
        """1. Python runtime, Virtual Environment, and Disk usage."""
        self.log_header("1. SYSTEM & PYTHON RUNTIME")
        ok = True

        ver_tuple = sys.version_info[:2]
        ver_str = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        if ver_tuple < self.MIN_PYTHON_VERSION:
            print(f"[FAIL] Python Version: {ver_str} (Requires >= {self.MIN_PYTHON_VERSION[0]}.{self.MIN_PYTHON_VERSION[1]})")
            ok = False
        else:
            print(f"[OK]   Python Version: {ver_str}")

        in_venv = sys.prefix != sys.base_prefix
        if not in_venv:
            print("[FAIL] Virtual Env: Inactive (Using global Python runtime)")
            print("       Fix: source work_venv/bin/activate")
            ok = False
        else:
            venv_name = Path(sys.prefix).name
            print(f"[OK]   Virtual Env: Active ({venv_name})")

        free_gb = shutil.disk_usage(self.target_dir).free / (1024 ** 3)
        if free_gb < 2.0:
            print(f"[WARN] Disk Space: Low ({free_gb:.1f} GB available)")
        else:
            print(f"[OK]   Disk Space: {free_gb:.1f} GB available")

        self.summary_status.append(("System & Python Runtime", ok))
        return ok

    def check_system_tools(self):
        """2. Required CLI tools."""
        self.log_header("2. SYSTEM CLI TOOLS")
        essential_tools = ["git", "curl", "ripgrep", "gcc", "make"]
        ok = True

        for tool in essential_tools:
            path = shutil.which(tool)
            if path:
                print(f"[OK]   {tool:<12} Found ({path})")
            else:
                print(f"[FAIL] {tool:<12} Missing (Run: sudo apt install {tool})")
                ok = False

        self.summary_status.append(("System Tools", ok))
        return ok

    def check_git_status(self):
        """3. Git workspace, user configuration, branch, and status."""
        self.log_header("3. GIT REPOSITORY & IDENTITY")

        if not shutil.which("git"):
            print("[FAIL] Git CLI unavailable.")
            self.summary_status.append(("Git Workspace", False))
            return False

        git_check = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=self.target_dir, capture_output=True, text=True
        )
        if git_check.returncode != 0:
            print("[FAIL] Git Repo: Not initialized in this directory.")
            print("       Fix: git init")
            self.summary_status.append(("Git Workspace", False))
            return False

        print("[OK]   Git Repo: Initialized")

        name = subprocess.run(["git", "config", "user.name"], cwd=self.target_dir, capture_output=True, text=True).stdout.strip()
        email = subprocess.run(["git", "config", "user.email"], cwd=self.target_dir, capture_output=True, text=True).stdout.strip()

        identity_ok = True
        if not name or not email:
            print("[FAIL] Git Identity: Incomplete")
            if not name:
                print("       Missing user.name  -> Set: git config --global user.name 'Your Name'")
            if not email:
                print("       Missing user.email -> Set: git config --global user.email 'you@example.com'")
            identity_ok = False
        else:
            print(f"[OK]   Git Identity: {name} <{email}>")

        branch = subprocess.run(["git", "branch", "--show-current"], cwd=self.target_dir, capture_output=True, text=True).stdout.strip()
        print(f"[INFO] Branch: {branch if branch else 'HEAD (no commits yet)'}")

        status = subprocess.run(["git", "status", "--porcelain"], cwd=self.target_dir, capture_output=True, text=True).stdout.strip()
        if status:
            count = len(status.splitlines())
            print(f"[WARN] Working Tree: Dirty ({count} uncommitted file changes/untracked files)")
        else:
            print("[OK]   Working Tree: Clean")

        self.summary_status.append(("Git Workspace", identity_ok))
        return identity_ok

    def check_secrets_and_env(self):
        """4. Security check for .env files and gitignore protection."""
        self.log_header("4. SECRETS & ENVIRONMENT SECURITY")
        env_file = self.target_dir / ".env"
        gitignore = self.target_dir / ".gitignore"

        if not env_file.exists():
            print("[INFO] Secrets: No .env file found in target path.")
            self.summary_status.append(("Secrets & Security", True))
            return True

        print("[INFO] Secrets: .env file detected.")
        is_ignored = False
        if gitignore.exists():
            with open(gitignore, "r", encoding="utf-8") as f:
                lines = [line.strip() for line in f.readlines()]
                if ".env" in lines or "*.env" in lines:
                    is_ignored = True

        if is_ignored:
            print("[OK]   Gitignore: .env is excluded from version control.")
        else:
            print("[FAIL] DANGER: .env file exists but is NOT listed in .gitignore.")
            print("       Fix: echo '.env' >> .gitignore")

        keys = []
        with open(env_file, "r", encoding="utf-8") as f:
            for line in f:
                if "=" in line and not line.startswith("#"):
                    k = line.split("=")[0].strip()
                    if k:
                        keys.append(k)

        if keys:
            print(f"[INFO] Loaded Keys: {', '.join(keys)}")

        self.summary_status.append(("Secrets & Security", is_ignored))
        return is_ignored

    def check_dependencies(self):
        """5. Scans code or requirements.txt for external Python dependencies."""
        self.log_header("5. PYTHON DEPENDENCIES & AST SCAN")
        req_file = self.target_dir / "requirements.txt"
        modules = set()
        syntax_ok = True

        if req_file.exists():
            source = "requirements.txt"
            with open(req_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith(("#", "-i", "--")):
                        pkg = line.split("==")[0].split(">=")[0].split("<=")[0].split("~=")[0].strip()
                        if pkg:
                            modules.add(pkg)
        else:
            source = "AST Code Scan"
            local_files = {p.stem for p in self.target_dir.rglob("*.py")}
            for py_file in self.target_dir.rglob("*.py"):
                if any(p in py_file.parts for p in ["venv", ".venv", "__pycache__", ".git"]):
                    continue
                try:
                    with open(py_file, "r", encoding="utf-8") as f:
                        tree = ast.parse(f.read(), filename=str(py_file))
                    for node in ast.walk(tree):
                        if isinstance(node, ast.Import):
                            for alias in node.names:
                                modules.add(alias.name.split(".")[0])
                        elif isinstance(node, ast.ImportFrom) and node.module:
                            modules.add(node.module.split(".")[0])
                except SyntaxError as e:
                    print(f"[WARN] Syntax Error in {py_file.name} at line {e.lineno}")
                    syntax_ok = False
                except Exception:
                    continue

            modules = {m for m in modules if m not in self.STDLIB_MODULES and m not in local_files}

        if not modules:
            print("[INFO] No external Python packages detected.")
            self.summary_status.append(("Dependencies", syntax_ok))
            return syntax_ok

        print(f"[INFO] Source: {source} ({len(modules)} package targets)\n")
        missing = []

        for mod in sorted(modules):
            lookup_name = self.PACKAGE_MAPPINGS.get(mod.lower(), mod)
            installed = importlib.util.find_spec(lookup_name) is not None
            if not installed and lookup_name != mod:
                installed = importlib.util.find_spec(mod) is not None

            if installed:
                print(f"[OK]   {mod:<20} Installed")
            else:
                print(f"[FAIL] {mod:<20} Missing")
                missing.append(self.PACKAGE_MAPPINGS.get(mod, mod))

        if missing:
            print(f"\n       Fix missing: pip install {' '.join(missing)}")

        deps_ok = (len(missing) == 0) and syntax_ok
        self.summary_status.append(("Dependencies", deps_ok))
        return deps_ok

    def check_repo_hygiene(self):
        """6. Large file scanner (>50MB) and build/cache folder check."""
        self.log_header("6. REPO HYGIENE & LARGE FILES")
        large_files = []
        cache_folders = []

        for p in self.target_dir.rglob("*"):
            if any(part in p.parts for part in ["venv", ".venv", ".git"]):
                continue

            if p.is_file():
                mb = p.stat().st_size / (1024 * 1024)
                if mb > self.MAX_FILE_SIZE_MB:
                    large_files.append((p.name, mb))
            elif p.is_dir() and p.name in ["__pycache__", ".ipynb_checkpoints", "build", "dist"]:
                cache_folders.append(p.name)

        hygiene_ok = True
        if large_files:
            print(f"[WARN] Large files detected (>{int(self.MAX_FILE_SIZE_MB)} MB):")
            for name, size in large_files:
                print(f"       • {name} ({size:.1f} MB)")
            hygiene_ok = False
        else:
            print(f"[OK]   No oversized binaries (>{int(self.MAX_FILE_SIZE_MB)} MB)")

        if cache_folders:
            print(f"[INFO] Cache/build folders present: {set(cache_folders)}")
        else:
            print("[OK]   Workspace cache structure clean")

        self.summary_status.append(("Repo Hygiene", hygiene_ok))
        return hygiene_ok

    def run_all(self):
        """Runs all checks and prints an executive summary block."""
        print("==================================================")
        print("           WORKSPACE ENVIRONMENT DOCTOR           ")
        print("==================================================")

        self.check_system_and_python()
        self.check_system_tools()
        self.check_git_status()
        self.check_secrets_and_env()
        self.check_dependencies()
        self.check_repo_hygiene()

        print("\n==================================================")
        print("                  SYSTEM SUMMARY                  ")
        print("==================================================")
        all_passed = True
        for section, passed in self.summary_status:
            status = "PASS" if passed else "FAIL/WARN"
            if not passed:
                all_passed = False
            print(f"  {section:<28} : [{status}]")

        print("--------------------------------------------------")
        if all_passed:
            print("  OVERALL STATUS             : ALL SYSTEMS GO")
        else:
            print("  OVERALL STATUS             : ACTION REQUIRED")
        print("==================================================\n")


# For organize project in python
import ast
import importlib.metadata
import os
import shutil
import socket
import sys
from pathlib import Path
from typing import Optional
from pydantic import BaseModel, Field
from langchain_core.tools import tool


class ProjectOrganizer:
    """Consolidated engine to clean, check connectivity, sync requirements, and organize workspace structure."""

    STDLIB_MODULES = set(sys.builtin_module_names) | {
        "ast", "argparse", "asyncio", "collections", "copy", "csv", "datetime",
        "functools", "importlib", "io", "itertools", "json", "logging", "math",
        "multiprocessing", "os", "pathlib", "random", "re", "shutil", "socket",
        "string", "subprocess", "sys", "threading", "time", "typing", "unittest"
    }

    PACKAGE_MAPPINGS = {
        "bs4": "beautifulsoup4",
        "sklearn": "scikit-learn",
        "PIL": "pillow",
        "cv2": "opencv-python",
        "yaml": "pyyaml",
        "dotenv": "python-dotenv",
        "fitz": "pymupdf",
        "docx": "python-docx",
        "google.generativeai": "google-generativeai",
        "langchain_core": "langchain-core",
        "langchain_groq": "langchain-groq"
    }

    def __init__(self, target_path: str = "."):
        # 1. Safely convert to string and strip quotes
        clean_path = str(target_path).strip("'\"")
        
        # 2. Resolve the path properly
        self.target_dir = Path(clean_path).expanduser().resolve()

    def clean_junk(self) -> str:
        """Removes temporary cache directories and compiled files."""
        if not self.target_dir.exists():
            return f"Error: Target directory path does not exist: {self.target_dir}"

        removed_dirs = 0
        removed_files = 0

        for target in self.target_dir.rglob("*"):
            if any(p in target.parts for p in ["venv", ".venv", ".git"]):
                continue

            if target.is_dir() and target.name in ["__pycache__", ".ipynb_checkpoints", ".pytest_cache", "build", "dist", ".egg-info"]:
                try:
                    shutil.rmtree(target)
                    removed_dirs += 1
                except Exception:
                    pass

        for file_path in self.target_dir.rglob("*.pyc"):
            if any(p in file_path.parts for p in ["venv", ".venv", ".git"]):
                continue
            try:
                file_path.unlink()
                removed_files += 1
            except Exception:
                pass

        return f"Removed {removed_dirs} cache directories and {removed_files} .pyc files."

    def check_connectivity(self, timeout_seconds: float = 2.0) -> str:
        """Tests socket connection to Groq, OpenAI, Gemini, and GitHub endpoints."""
        endpoints = {
            "Groq API": ("api.groq.com", 443),
            "OpenAI API": ("api.openai.com", 443),
            "Google Gemini API": ("generativelanguage.googleapis.com", 443),
            "GitHub": ("github.com", 443)
        }

        results = []
        for name, (host, port) in endpoints.items():
            try:
                sock = socket.create_connection((host, port), timeout=timeout_seconds)
                sock.close()
                results.append(f"[OK]   {name:<20} Connected")
            except Exception:
                results.append(f"[FAIL] {name:<20} Unreachable")

        return "\n".join(results)

    def sync_requirements(self) -> str:
        """Scans code imports, checks installed versions, and writes/updates requirements.txt."""
        if not self.target_dir.exists():
            return f"Error: Target directory path does not exist: {self.target_dir}"

        detected_modules = set()
        local_files = {p.stem for p in self.target_dir.rglob("*.py")}

        for py_file in self.target_dir.rglob("*.py"):
            if any(p in py_file.parts for p in ["venv", ".venv", "__pycache__", ".git"]):
                continue
            try:
                with open(py_file, "r", encoding="utf-8") as f:
                    tree = ast.parse(f.read(), filename=str(py_file))
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            detected_modules.add(alias.name.split(".")[0])
                    elif isinstance(node, ast.ImportFrom) and node.module:
                        detected_modules.add(node.module.split(".")[0])
            except Exception:
                continue

        external_packages = {
            self.PACKAGE_MAPPINGS.get(m.lower(), m)
            for m in detected_modules
            if m not in self.STDLIB_MODULES and m not in local_files
        }

        if not external_packages:
            return "No third-party packages detected."

        package_entries = []
        for pkg in sorted(external_packages):
            lookup_name = self.PACKAGE_MAPPINGS.get(pkg.lower(), pkg)
            try:
                ver = importlib.metadata.version(lookup_name)
                package_entries.append(f"{lookup_name}=={ver}")
            except importlib.metadata.PackageNotFoundError:
                package_entries.append(f"{lookup_name}")

        req_file = self.target_dir / "requirements.txt"
        existed = req_file.exists()

        with open(req_file, "w", encoding="utf-8") as f:
            f.write("# Auto-generated & synced by Jarvis Agent\n")
            for entry in package_entries:
                f.write(f"{entry}\n")

        action = "Updated" if existed else "Created"
        return f"{action} requirements.txt with {len(package_entries)} active packages."

    def ensure_workspace_files(self) -> str:
        """Ensures essential project files (.gitignore, .env.example) exist."""
        if not self.target_dir.exists():
            return f"Error: Target directory path does not exist: {self.target_dir}"

        gitignore_path = self.target_dir / ".gitignore"
        env_example_path = self.target_dir / ".env.example"

        created = []

        if not gitignore_path.exists():
            with open(gitignore_path, "w", encoding="utf-8") as f:
                f.write("__pycache__/\n*.pyc\n.env\nvenv/\n.venv/\n.ipynb_checkpoints/\nbuild/\ndist/\n")
            created.append(".gitignore")

        if not env_example_path.exists():
            with open(env_example_path, "w", encoding="utf-8") as f:
                f.write("# API Keys Template\nGROQ_API_KEY=your_key_here\nOPENAI_API_KEY=your_key_here\nGEMINI_API_KEY=your_key_here\n")
            created.append(".env.example")

        if created:
            return f"Created config templates: {', '.join(created)}"
        return "Workspace config files (.gitignore, .env.example) are present."



# GIT PUSH COMMIT 
import os
import subprocess
import json
import requests

class GitAssistant:
    """
    A Git Assistant with strict token-budget protections.
    Prevents large diffs, datasets, and lockfiles from blowing up LLM context/costs.
    """

    # Files to completely ignore during diff generation to save tokens
    EXCLUDE_PATTERNS = [
        ":!*.json", ":!*.csv", ":!*.tsv", ":!*.parquet",
        ":!*.pt", ":!*.pth", ":!*.onnx", ":!*.bin", ":!*.h5",
        ":!*.ipynb", ":!package-lock.json", ":!poetry.lock", ":!yarn.lock", ":!Cargo.lock"
    ]

    def __init__(
        self, 
        repo_path: str = ".", 
        groq_api_key: str = None, 
        max_diff_chars: int = 2500,  # ~500–600 tokens budget max for diff
        model_name: str = "llama-3.1-8b-instant"  # Fastest & cheapest model
    ):
        self.repo_path = os.path.abspath(repo_path)
        self.groq_api_key = groq_api_key or os.getenv("GROQ_API_KEY")
        self.groq_url = "https://api.groq.com/openai/v1/chat/completions"
        self.max_diff_chars = max_diff_chars
        self.model_name = model_name

    def _run_git(self, args: list) -> tuple[bool, str]:
        """Runs a git command inside the target repo directory."""
        try:
            result = subprocess.run(
                ["git"] + args,
                cwd=self.repo_path,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=True
            )
            return True, result.stdout.strip()
        except subprocess.CalledProcessError as e:
            error_msg = e.stderr.strip() or e.stdout.strip()
            return False, error_msg

    def is_git_repo(self) -> bool:
        """Verifies if directory is a valid git repository."""
        success, _ = self._run_git(["rev-parse", "--is-inside-work-tree"])
        return success

    def is_first_commit(self) -> bool:
        """Checks if repo has zero commits (brand new repo)."""
        success, _ = self._run_git(["rev-parse", "HEAD"])
        return not success

    def stage_all(self) -> tuple[bool, str]:
        """Stages all changes."""
        return self._run_git(["add", "."])

    # Correct
    def get_safe_diff(self) -> tuple[str, str]:
        """
        Fetches the git diff using strict token filters.
        Returns: (diff_content, diff_type) where diff_type is 'full' or 'stat'
        """
        # Base command excluding heavy lock/data files
        cmd = ["diff", "--cached", "--"] + self.EXCLUDE_PATTERNS
        success, diff_text = self._run_git(cmd)

        if not success or not diff_text.strip():
            # If standard diff empty, check if untracked files exist
            success, diff_text = self._run_git(["diff", "--cached"])

        # SAFEGUARD: If raw diff is too large, fall back to file stats summary (--stat)
        if len(diff_text) > self.max_diff_chars:
            print(f"[Token Guard] Diff size ({len(diff_text)} chars) exceeds budget limit.")
            print("[Token Guard] Switching to lightweight '--stat' mode to save tokens...")
            
            stat_cmd = ["diff", "--cached", "--stat"]
            _, stat_text = self._run_git(stat_cmd)
            return stat_text, "stat"

        return diff_text, "full"

    def generate_commit_message(self, diff_text: str, diff_type: str) -> str:
        """
        Sends guarded diff to LLM and returns commit message.
        """
        # Layer 1: Local handling for empty diffs
        if not diff_text.strip():
            return "Chore: routine update and minor cleanups"

        # Layer 2: Local handling for first commit (0 tokens consumed)
        if self.is_first_commit():
            return "Initial commit: initialize project structure and baseline files"

        if not self.groq_api_key:
            raise ValueError("GROQ_API_KEY environment variable is not set.")

        system_prompt = (
            "You are an expert developer assistant. Write a concise, single-line conventional commit message "
            "(e.g., feat:, fix:, refactor:, docs:, chore:) based on the provided git changes. "
            "Return ONLY the commit message string without quotes or conversational text."
        )

        # Layer 3: Hard character truncation guardrail
        safe_payload = diff_text[:self.max_diff_chars]

        user_content = (
            f"Git Changes Summary:\n{safe_payload}" 
            if diff_type == "stat" 
            else f"Git Code Diff:\n{safe_payload}"
        )

        headers = {
            "Authorization": f"Bearer {self.groq_api_key}",
            "Content-Type": "application/json"
        }

        payload = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content}
            ],
            "max_tokens": 60,  # Limits model output tokens
            "temperature": 0.2
        }

        try:
            response = requests.post(self.groq_url, headers=headers, json=payload, timeout=8)
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"].strip()
        except Exception as e:
            print(f"[Warning] API call failed ({e}). Falling back to local message.")
            return "Chore: automated code update"

    def commit(self, message: str) -> tuple[bool, str]:
        """Executes git commit."""
        return self._run_git(["commit", "-m", message])

    def push(self) -> tuple[bool, str]:
        """Pushes to remote branch."""
        return self._run_git(["push"])

    def auto_commit_and_push(self, custom_message: str = None) -> dict:
        """Main execution function triggered by Jarvis."""
        if not self.is_git_repo():
            return {"status": "error", "message": "Not a valid Git repository."}

        # Step 1: Stage
        add_ok, add_err = self.stage_all()
        if not add_ok:
            return {"status": "error", "message": f"Staging failed: {add_err}"}

        # Step 2: Get Guarded Diff
        diff_text, diff_type = self.get_safe_diff()

        # Step 3: Determine Commit Message
        if custom_message:
            commit_msg = custom_message
        else:
            commit_msg = self.generate_commit_message(diff_text, diff_type)

        # Step 4: Commit
        commit_ok, commit_err = self.commit(commit_msg)
        if not commit_ok:
            return {"status": "info/error", "message": f"Nothing committed or failed: {commit_err}"}

        # Step 5: Push
        push_ok, push_err = self.push()
        if not push_ok:
            return {
                "status": "warning", 
                "message": f"Committed locally as '{commit_msg}', but push failed: {push_err}"
            }

        return {
            "status": "success",
            "commit_message": commit_msg,
            "diff_mode_used": diff_type,
            "message": "Successfully committed and pushed code to GitHub!"
        }
    # Add this method back inside TokenGuardedGitAssistant class:
    def summarize_today_changes(self) -> str:
        """Session Recall feature: Summarizes today's commits."""
        success, logs = self._run_git(["log", "--since=midnight", "--oneline"])
        if not success or not logs.strip():
            return "No commits logged today yet."
        return f"Commits made today:\n{logs}"




# Test by pytest
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional


class TestRunnerController:
    """Executes pytest, parses failure traces, and reads failing files for immediate debugging."""

    def __init__(self, project_dir: str = "."):
        resolved_path = Path(os.path.expanduser(project_dir.strip("'\""))).resolve()

        # FIX: If user/LLM passes a direct file path instead of a directory, handle it gracefully!
        if resolved_path.is_file():
            self.project_dir = resolved_path.parent
            self.direct_file_target = resolved_path
        else:
            self.project_dir = resolved_path
            self.direct_file_target = None

    def run_pytest_and_diagnose(
        self,
        test_path: Optional[str] = None,
        test_pattern: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Runs pytest on a target path or pattern."""
        if not self.project_dir.exists():
            return {
                "status": "error",
                "message": f"Project path '{self.project_dir}' does not exist.",
            }

        # Build pytest command
        cmd = ["pytest", "--tb=short", "-q"]

        # If a direct file was passed during __init__, prioritize it
        if self.direct_file_target:
            cmd.append(str(self.direct_file_target))
        elif test_path:
            full_target = (self.project_dir / test_path).resolve()
            cmd.append(str(full_target))

        if test_pattern:
            cmd.extend(["-k", test_pattern])

        try:
            result = subprocess.run(
                cmd,
                cwd=str(self.project_dir),  # ✅ Guaranteed to be a valid directory now!
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=30,
            )

            stdout = result.stdout.strip()
            stderr = result.stderr.strip()

            if result.returncode == 0:
                return {
                    "status": "success",
                    "summary": "All tests passed! ✅",
                    "output": stdout,
                }

            elif result.returncode == 1:
                failure_output = stdout or stderr
                failing_file, code_snippet = self._extract_and_read_failing_file(
                    failure_output
                )

                return {
                    "status": "failed",
                    "summary": "Some tests failed ❌",
                    "traceback": failure_output,
                    "failing_file": failing_file,
                    "source_code": code_snippet,
                }

            elif result.returncode == 5:
                return {
                    "status": "no_tests",
                    "summary": "No matching tests found ⚠️",
                    "output": stdout or stderr,
                }

            else:
                return {
                    "status": "error",
                    "summary": f"Pytest exit code: {result.returncode}",
                    "output": stderr or stdout,
                }

        except subprocess.TimeoutExpired:
            return {
                "status": "error",
                "summary": "Test execution timed out after 30 seconds.",
            }
        except FileNotFoundError:
            return {
                "status": "error",
                "summary": "'pytest' is not installed in the active virtual environment.",
            }

    def _extract_and_read_failing_file(
        self, failure_output: str
    ) -> tuple[Optional[str], Optional[str]]:
        """Parses pytest traceback to find the primary failing file and reads its content."""
        file_match = re.search(r"([\w/\.-]+\.py):\d+:", failure_output)

        if file_match:
            relative_file_path = file_match.group(1)
            file_path = (self.project_dir / relative_file_path).resolve()

            if file_path.exists() and file_path.is_file():
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        lines = f.readlines()
                        content = "".join(lines[:100])
                        return str(relative_file_path), content
                except Exception:
                    pass

        return None, None

 # IPYNB TO PY
import os
import nbformat
from typing import Optional, Dict, Any


class NotebookScriptConverter:
    """Core logic engine to parse Jupyter notebooks and transform them into clean Python scripts."""

    def __init__(self, notebook_path: str, output_path: Optional[str] = None):
        self.notebook_path = notebook_path
        self.output_path = output_path or (os.path.splitext(notebook_path)[0] + ".py")

    def _clean_ipython_magics(self, code: str) -> str:
        """Comments out IPython magic commands (%) and shell commands (!)."""
        cleaned_lines = []
        for line in code.splitlines():
            stripped = line.strip()
            if stripped.startswith("%") or stripped.startswith("!"):
                cleaned_lines.append(f"# {line}  # Removed IPython magic/shell call")
            else:
                cleaned_lines.append(line)
        return "\n".join(cleaned_lines)

    def convert(self) -> Dict[str, Any]:
        """Executes the conversion process.

        Returns a status dictionary.
        """
        if not os.path.exists(self.notebook_path):
            return {
                "success": False,
                "message": f"Notebook file not found at '{self.notebook_path}'.",
            }

        if not self.notebook_path.endswith(".ipynb"):
            return {
                "success": False,
                "message": f"'{self.notebook_path}' is not a valid .ipynb file.",
            }

        try:
            with open(self.notebook_path, "r", encoding="utf-8") as f:
                nb = nbformat.read(f, as_version=4)

            python_code_blocks = [
                f"# =================== Notebook: {os.path.basename(self.notebook_path)} ===================\n"
            ]

            cell_count = 0
            for cell in nb.cells:
                if cell.cell_type == "code" and cell.source.strip():
                    cell_count += 1
                    cleaned_code = self._clean_ipython_magics(cell.source)

                    python_code_blocks.append(f"# --- Cell {cell_count} ---")
                    python_code_blocks.append(cleaned_code)
                    python_code_blocks.append("\n")

            if cell_count == 0:
                return {
                    "success": False,
                    "message": f"No valid code cells found in '{self.notebook_path}'.",
                }

            final_script = "\n".join(python_code_blocks)
            with open(self.output_path, "w", encoding="utf-8") as f:
                f.write(final_script)

            return {
                "success": True,
                "message": f"Successfully converted '{self.notebook_path}' -> '{self.output_path}' ({cell_count} code cells processed).",
                "output_path": self.output_path,
                "cell_count": cell_count,
            }

        except Exception as e:
            return {
                "success": False,
                "message": f"Failed to convert notebook: {str(e)}",
            }