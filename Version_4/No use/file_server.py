import os
import shutil
import pathlib
import fnmatch
from typing import List, Optional, Union
import platform,subprocess
from fastmcp import FastMCP

# Initialize the server
mcp = FastMCP("Jarvis_FileSystem")

IGNORE_PATTERNS = [
    "PostgreSQL", "site-packages", "node_modules", 
    "__pycache__", ".git", "$RECYCLE.BIN", "AppData", "Temp"
]

def is_ignored(path: str) -> bool:
    """Checks if a path should be hidden from Jarvis."""
    return any(pattern.lower() in path.lower() for pattern in IGNORE_PATTERNS)

def smart_path_resolve(path_str: str) -> str:
    """
    Forcefully resolves paths by matching names case-insensitively 
    against the actual file system.
    """
    # 1. Basic Cleanup
    path_str = path_str.strip().strip('"').strip("'")
    if " drive" in path_str.lower():
        path_str = path_str.lower().replace(" drive", ":")
    
    parts = pathlib.Path(path_str).parts
    if not parts:
        return path_str

    # 2. Start from the Root (e.g., D:\)
    current_path = pathlib.Path(parts[0])
    
    # 3. Iteratively find the real name for each part of the path
    for part in parts[1:]:
        if not current_path.exists():
            break
            
        found = False
        # Look at every item in the current directory
        for entry in os.scandir(current_path):
            # Check if names match (ignoring case)
            if entry.name.lower() == part.lower():
                current_path = pathlib.Path(entry.path)
                found = True
                break
        
        if not found:
            # If not found, append the part as-is and hope for the best
            current_path = current_path / part

    return str(current_path)

def normalize_path(path: str) -> str:
    """
    Standardizes paths for Windows compatibility.
    Converts 'D drive' to 'D:\' and fixes slashes.
    """
    # Remove quotes and extra spaces
    path = path.strip().strip('"').strip("'")
    
    # Convert 'D drive' or 'd drive' to 'D:'
    if " drive" in path.lower():
        # Replaces 'D drive' with 'D:'
        path = path.lower().replace(" drive", ":")
    
    # Ensure backslashes for Windows
    path = path.replace("/", "\\")
    
    # Handle cases like 'D:learning' -> 'D:\learning'
    if len(path) > 1 and path[1] == ":" and (len(path) == 2 or path[2] != "\\"):
        path = path[:2] + "\\" + path[2:]

    return os.path.normpath(path)

@mcp.tool()
def create_folder(path: str):
    """Creates a folder at the specified location."""
    os.makedirs(path, exist_ok=True)
    return f"Folder created successfully at: {path}"

@mcp.tool()
def write_file(path: str, content: str):
    """
    Creates/Overwrites a file. 
    If folders in the path don't exist, it creates them.
    """
    try:
        # Use our smart resolver to fix casing/path issues
        resolved_path = smart_path_resolve(path)
        p = pathlib.Path(resolved_path)

        # Ensure the content isn't just a placeholder string like "Task 3 content"
        if not content or len(content.strip()) < 2:
            return "Error: Content is empty. Please provide the actual code to write."

        # Create parent folders if they don't exist
        p.parent.mkdir(parents=True, exist_ok=True)

        with open(p, "w", encoding="utf-8") as f:
            f.write(content)
            
        return f"Successfully wrote {len(content)} characters to {resolved_path}"
    except Exception as e:
        return f"Failed to write file: {str(e)}"

@mcp.tool()
def move_item(source: str, destination: str):
    """Moves a file or folder from source to destination."""
    src = smart_path_resolve(source)
    shutil.move(src, destination)
    return f"Moved from {source} to {destination}"

@mcp.tool()
def read_path_content(path: str):
    """
    USE THIS TO GIVE JARVIS CONTEXT. 
    It reads the text inside a file so Jarvis can 'see' the code/text.
    """
    p = pathlib.Path(path)
    if not p.exists():
        return "File does not exist."
    
    if p.is_file():
        # Prevent Jarvis from trying to 'read' a 1GB video or image as text
        if p.suffix.lower() in ['.jpg', '.png', '.exe', '.zip', '.pdf']:
            return f"This is a binary file ({p.suffix}). Use 'open_file_externally' to see it."
            
        try:
            with open(p, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
                # Limit content size so we don't crash the LLM context
                return content[:10000] + "\n... (truncated)" if len(content) > 10000 else content
        except Exception as e:
            return f"Could not read file: {str(e)}"
    return "This path is a directory, not a file."

@mcp.tool()
def list_directory(path: str = "."):
    """Gives a clean list of files and folders in a path."""
    resolved = smart_path_resolve(path)
    items = os.listdir(resolved)
    return {"path": resolved, "items": items}

@mcp.tool()
def search_files(root_dir: str, pattern: str):
    """
    Recursive search. 
    Example: search_files("D:\\", "tools.py")
    """
    root = normalize_path(root_dir)
    matches = []
    
    # CRITICAL: We must use os.walk to go deep into folders
    # and skip heavy/system folders to avoid freezing.
    ignore = ["$recycle.bin", "system volume information", "node_modules", "postgresql", "site-packages"]
    
    for r, dirs, files in os.walk(root):
        # Filter directories to skip ignored ones
        dirs[:] = [d for d in dirs if d.lower() not in ignore]
        
        for f in files:
            if f.lower() == pattern.lower():
                matches.append(os.path.join(r, f))
        
        # Stop if we find too many to prevent token overflow
        if len(matches) > 10:
            break
            
    return matches if matches else f"File '{pattern}' not found in {root_dir} (Checked user folders only)."

@mcp.tool()
def open_file_externally(path: str):
    """
    Force-opens a file using the Windows Shell to ensure it appears on screen.
    """
    try:
        # 1. Use the smart resolver we built to get the REAL path
        true_path = smart_path_resolve(path) 
        p = pathlib.Path(true_path).absolute()

        if not p.exists():
            return f"Error: {p} does not exist on disk."

        if platform.system() == "Windows":
            try:
                # Method A: Standard Startfile
                os.startfile(str(p))
            except Exception:
                # Method B: PowerShell Force-Start (Better for background processes)
                # This explicitly tells Windows to 'invoke' the item via the shell
                subprocess.run(['powershell', '-Command', f'Start-Process "{str(p)}"'], check=True)
        else:
            # macOS/Linux logic
            cmd = "open" if platform.system() == "Darwin" else "xdg-open"
            subprocess.call([cmd, str(p)])
            
        return f"Successfully triggered opening of {p.name}"

    except Exception as e:
        return f"System failed to launch file: {str(e)}"
            
    return matches if matches else "No user files found matching that pattern."
if __name__ == "__main__":
    mcp.run()