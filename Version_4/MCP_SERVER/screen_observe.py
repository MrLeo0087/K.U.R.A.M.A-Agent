import pyautogui
import pytesseract
import os
from PIL import Image
from mcp.server.fastmcp import FastMCP
import time

# --- CONFIGURATION ---
# Point this to where you installed Tesseract
pytesseract.pytesseract.tesseract_cmd = r'D:\Learning\Test\Advance kurama automatic\MCP server\extra\tesseract.exe'

mcp = FastMCP("ScreenObserver")

@mcp.tool()
def take_screenshot(filename: str = "last_screenshot.png"):
    """
    Takes a screenshot of the entire primary monitor.
    Returns the file path.
    """
    screenshot = pyautogui.screenshot()
    path = os.path.join(os.getcwd(), filename)
    screenshot.save(path)
    return f"Screenshot saved successfully at: {path}"

# @mcp.tool()
# def read_screen_text():
#     """
#     Captures the screen and uses OCR to extract all visible text.
#     Useful for 'reading' error messages or website content.
#     """
#     screenshot = pyautogui.screenshot()
#     # Convert image to grayscale for better OCR accuracy
#     text = pytesseract.image_to_string(screenshot)
    
#     if not text.strip():
#         return "The screen appears to be empty or contains only images (no text found)."
    
#     return f"Extracted Text from Screen:\n\n{text}"

from PIL import Image

@mcp.tool()
def read_image_file_text(image_path: str):
    """
    Reads a specific image file from your computer and extracts the text.
    """
    try:
        # Open the image file from the path
        img = Image.open(image_path)
        
        # Extract text
        text = pytesseract.image_to_string(img)
        
        if not text.strip():
            return "No text detected in this image."
            
        return f"Text found in {image_path}:\n\n{text}"
    except Exception as e:
        return f"Error opening image: {str(e)}"

@mcp.tool()
def find_text_on_screen(target_text: str):
    """
    Checks if a specific word or phrase is currently visible on the screen.
    """
    screenshot = pyautogui.screenshot()
    text = pytesseract.image_to_string(screenshot)
    
    if target_text.lower() in text.lower():
        return f"Yes, '{target_text}' was found on your screen."
    else:
        return f"No, '{target_text}' is not currently visible."

@mcp.tool()
def get_mouse_position():
    """Returns the current X and Y coordinates of the mouse cursor."""
    x, y = pyautogui.position()
    return f"The cursor is at X: {x}, Y: {y}"

if __name__ == "__main__":
    mcp.run()