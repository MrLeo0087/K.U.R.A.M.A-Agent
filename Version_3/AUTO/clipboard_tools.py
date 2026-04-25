# NODE/auto/tools/clipboard_tools.py
import pyperclip
from langchain_core.tools import tool

@tool
def get_clipboard() -> str:
    """Get the current text stored in the system clipboard.
    
    Use when user says 'use my copied text', 'what did I copy',
    'use clipboard', 'paste that', 'use what I copied'.
    
    Examples:
        - "save my clipboard to a file"  → get_clipboard()
        - "translate what I copied"      → get_clipboard()
        - "what's in my clipboard?"      → get_clipboard()
    """
    text = pyperclip.paste()
    return text if text.strip() else "Clipboard is empty."


@tool
def set_clipboard(text: str) -> str:
    """Copy any text into the system clipboard.
    
    Use when user says 'copy this to clipboard', 'save to clipboard',
    'put this in my clipboard', 'copy the result'.
    
    Examples:
        - "copy this poem to clipboard"   → set_clipboard("poem text...")
        - "save result to clipboard"      → set_clipboard("result...")
        - "put this code in clipboard"    → set_clipboard("code...")
    """
    pyperclip.copy(text)
    return "Copied to clipboard successfully."