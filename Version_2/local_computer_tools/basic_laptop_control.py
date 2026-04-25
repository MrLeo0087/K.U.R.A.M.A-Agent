from langchain.tools import tool
import pyautogui
from typing import Optional
import screen_brightness_control as sbc

@tool
def basic_control(command: str, value: Optional[int] = 5):
    """
    Controls system hardware like volume, brightness, and screen mode.
    
    Parameters:
    - command: The action to perform ('mute', 'volumeup', 'volumedown', 'fullscreen', 'brightnessincrease', 'brightnessdecrease')
    - value: The percentage to increase/decrease (default is 5).
    """
    
    # Clean the command to prevent matching errors
    cmd = command.lower().strip()

    # --- VOLUME CONTROLS ---
    if cmd == 'mute':
        pyautogui.press('volumemute')
        return "System muted/unmuted successfully."

    if cmd == 'volumeup':
        # Press the volume up key 'value' times (approximate percentage)
        for _ in range(max(1, value // 2)): 
            pyautogui.press('volumeup')
        return f"Volume increased by approx {value}%."

    if cmd == 'volumedown':
        for _ in range(max(1, value // 2)):
            pyautogui.press('volumedown')
        return f"Volume decreased by approx {value}%."

    # --- DISPLAY CONTROLS ---
    if cmd == 'fullscreen':
        pyautogui.press('f11')
        return "Toggled full screen mode."

    if cmd == 'brightnessincrease':
        current = sbc.get_brightness()[0]
        new_brightness = min(100, current + value)
        sbc.set_brightness(new_brightness)
        return f"Brightness increased to {new_brightness}%."

    if cmd == 'brightnessdecrease':
        current = sbc.get_brightness()[0]
        new_brightness = max(0, current - value)
        sbc.set_brightness(new_brightness)
        return f"Brightness decreased to {new_brightness}%."

    return f"Command '{command}' not recognized."

