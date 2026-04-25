from langchain.tools import tool
import time
import pyautogui

@tool
def open_app(name: str):
    """
    This function open any app in local pc/laptop

    Args:
        name: string
        description: name of app
        Example: - open photoshop (name : photoshop)
        - can you open this pc (name : this pc)
    """
    try:
        pyautogui.press('win')
        time.sleep(0.5)
        pyautogui.write(name,interval=0.01)
        time.sleep(2)
        pyautogui.press('enter')

        return f"{name} Opened! "

    except Exception as e:
        return f"Error : {e}"
    
