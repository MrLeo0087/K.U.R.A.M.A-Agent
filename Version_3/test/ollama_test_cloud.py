import ollama

def summarize_with_qwen():
    response = ollama.chat(
        model='qwen3.5:cloud',
        messages=[{'role': 'user', 'content': f"Hello, how are you?"}],
        options={'keep_alive': 0} # Unloads immediately to save your limit
    )
    return response['message']['content']


result = summarize_with_qwen()
print(result)