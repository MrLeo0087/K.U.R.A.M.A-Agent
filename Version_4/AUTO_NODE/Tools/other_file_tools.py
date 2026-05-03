from langchain.tools import tool
import subprocess
import os

# Global variable to store the process state across tool calls
running_processes = {}

@tool 
def youtube_vision_control(task: str):
    """Start or stop vision and hand gesture control for youtube and media control.
    task: 'start' to begin control, 'stop' to end it."""

    file_path = r"D:\My Future\Project\Gen_AI\02_K.U.R.A.M.A\Version_4\Extra_tools_file\Youtube_vision_control\main.py"
    global running_processes
    
    # Unique key for this specific tool's process
    proc_key = "youtube_vision"

    if task == 'start':
        # Check if process exists and is still running
        if proc_key in running_processes and running_processes[proc_key].poll() is None:
            return "Vision control is already running."
        
        try:
            print(f"--- Starting {file_path} ---")
            proc = subprocess.Popen(['python', file_path])
            running_processes[proc_key] = proc
            return f"Vision control started with PID: {proc.pid}"
        except Exception as e:
            return f"Failed to start: {str(e)}"

    elif task == 'stop':
        proc = running_processes.get(proc_key)
        if proc and proc.poll() is None:
            print(f"--- Stopping {file_path} (PID: {proc.pid}) ---")
            proc.terminate()
            proc.wait()
            del running_processes[proc_key]
            return "Vision control stopped successfully."
        else:
            return "No active vision control process found to stop."
            
    return "Invalid task. Please use 'start' or 'stop'."