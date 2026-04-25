from pynput import mouse

def on_click(x, y, button, pressed):
    if pressed:
        print(f"Mouse clicked at: ({x}, {y}) with {button}")
    # To stop the script, you can add logic here to return False

print("Listening for clicks... (Press Ctrl+C in the terminal to stop)")

# This creates a listener that runs in the background
with mouse.Listener(on_click=on_click) as listener:
    listener.join() 
