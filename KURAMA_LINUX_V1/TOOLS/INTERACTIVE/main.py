import subprocess

# Run 'ls -la' in the terminal
result = subprocess.run(
    ["sudo apt update"], 
    capture_output=True, 
    text=True
)

# Access the results
print("Exit Code:", result.returncode)  # 0 means success
print("Output:\n", result.stdout)