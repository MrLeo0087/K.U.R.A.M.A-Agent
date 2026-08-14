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
        clean_path = target_path.strip("'\"")
        self.target_dir = Path(os.path.abspath(os.path.expanduser(clean_path)))

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


# File create remove and search
import os
import shutil
from pathlib import Path
from typing import Optional, List, Dict

def resolve_safe_path(target_path: str) -> Path:
    raw_path = target_path.strip("'\"")
    
    # Expand tilde ~ to full home path (/home/leo)
    expanded = os.path.expanduser(raw_path)
    resolved = Path(os.path.abspath(expanded))
    
    # If LLM generates /home/file.py or /home/folder instead of /home/leo/folder
    user_home = Path.home() # Resolves to /home/leo
    if resolved.parent == Path("/home") and resolved != user_home:
        # Redirect /home/main.py -> /home/leo/main.py
        return user_home / resolved.name
        
    return resolved

class FileSystemManager:
    """Core engine for high-speed file search, creation, and safe deletion."""

    # Protected system paths that cannot be deleted under any circumstances
    PROTECTED_PATHS = {
        "/", "/bin", "/boot", "/dev", "/etc", "/lib", "/lib64", 
        "/proc", "/root", "/run", "/sbin", "/sys", "/usr", "/var", "/home",
        "C:\\", "C:\\Windows", "C:\\Program Files", "C:\\Program Files (x86)", "C:\\Users"
    }

    def __init__(self, base_path: str = "."):
        clean_path = base_path.strip("'\"")
        self.base_dir = Path(os.path.abspath(os.path.expanduser(clean_path)))

    def search_items(self, pattern: str, root_dir: Optional[str] = None, max_results: int = 50) -> List[Dict[str, str]]:
        """Fast file and directory search matching patterns or keywords across the system."""
        target_root = Path(os.path.abspath(os.path.expanduser(root_dir))) if root_dir else self.base_dir
        
        if not target_root.exists():
            return [{"error": f"Path does not exist: {target_root}"}]

        matches = []
        pattern_lower = pattern.lower()

        # Efficient traversal ignoring permission errors
        for root, dirs, files in os.walk(target_root, topdown=True, followlinks=False):
            # Skip heavy system/cache folders during search to keep speed high
            dirs[:] = [d for d in dirs if d not in {".git", "__pycache__", "node_modules", ".venv", "venv", "$RECYCLE.BIN"}]

            for item in dirs + files:
                if pattern_lower in item.lower():
                    full_path = Path(root) / item
                    matches.append({
                        "name": item,
                        "type": "directory" if full_path.is_dir() else "file",
                        "path": str(full_path)
                    })
                    if len(matches) >= max_results:
                        return matches

        return matches

    def create_item(self, target_path: str, is_directory: bool = False, content: str = "") -> str:
        clean_target = resolve_safe_path(target_path)

        try:
            if is_directory:
                # os.makedirs equivalent in pathlib
                clean_target.mkdir(parents=True, exist_ok=True)
                return f"Successfully created directory: {clean_target}"
            else:
                clean_target.parent.mkdir(parents=True, exist_ok=True)
                with open(clean_target, "w", encoding="utf-8") as f:
                    f.write(content or "")
                return f"Successfully created file: {clean_target} ({len(content or '')} characters)"
        except Exception as e:
            return f"Error creating item at {clean_target}: {str(e)}"

    def remove_item(self, target_path: str, recursive: bool = False) -> str:
        """Safely removes a file or directory with root-protection guardrails."""
        clean_target = Path(os.path.abspath(os.path.expanduser(target_path.strip("'\""))))

        # Guardrail Check 1: Must exist
        if not clean_target.exists():
            return f"Error: Target path does not exist: {clean_target}"

        # Guardrail Check 2: Protect system critical paths
        if str(clean_target) in self.PROTECTED_PATHS or clean_target == clean_target.anchor:
            return f"SECURITY BLOCKED: Cannot delete root/system path '{clean_target}'."

        try:
            if clean_target.is_file() or clean_target.is_symlink():
                clean_target.unlink()
                return f"Successfully deleted file: {clean_target}"
            elif clean_target.is_dir():
                if not recursive and any(clean_target.iterdir()):
                    return f"Error: Directory '{clean_target}' is not empty. Set recursive=True to delete."
                shutil.rmtree(clean_target)
                return f"Successfully deleted directory: {clean_target}"
            return f"Error: Path {clean_target} is neither file nor directory."
        except Exception as e:
            return f"Error deleting {clean_target}: {str(e)}"


# --------------------------------------------------
# LANGCHAIN TOOL WRAPPER
# --------------------------------------------------


