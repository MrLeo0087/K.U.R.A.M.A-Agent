import sys
import subprocess
import os
import tempfile
import threading
import time

# Ensure required packages are installed
def install(package):
    subprocess.check_call([sys.executable, "-m", "pip", "install", package])

try:
    import screen_brightness_control as sbc
except ImportError:
    install('screen_brightness_control')
    import screen_brightness_control as sbc

try:
    from PIL import Image
except ImportError:
    install('Pillow')
    from PIL import Image

try:
    import requests
except ImportError:
    install('requests')
    import requests

def set_brightness(value: int):
    """Set the primary monitor brightness to *value* (0‑100)."""
    try:
        sbc.set_brightness(value)
        print(f"Brightness set to {value}%")
    except Exception as e:
        print(f"Failed to set brightness: {e}")

def download_image(url: str) -> str:
    """Download image from *url* to a temporary file and return its path."""
    resp = requests.get(url, stream=True, timeout=15)
    resp.raise_for_status()
    fd, path = tempfile.mkstemp(suffix=os.path.splitext(url)[1])
    with os.fdopen(fd, 'wb') as tmp:
        for chunk in resp.iter_content(8192):
            tmp.write(chunk)
    return path

def show_image(path: str):
    """Open the image using Pillow's default viewer in a non‑blocking way."""
    img = Image.open(path)
    # Use a separate thread so the script can continue (or exit) without blocking the viewer.
    threading.Thread(target=img.show, daemon=True).start()

def main():
    while True:
        try:
            user_input = input("Enter desired brightness (0‑100): ").strip()
            if not user_input:
                continue
            value = int(user_input)
            if 0 <= value <= 100:
                break
            else:
                print("Please enter a number between 0 and 100.")
        except ValueError:
            print("Invalid input – please enter an integer.")

    set_brightness(value)

    # Cinematic bright image of a man flying in the sky (public domain / royalty‑free)
    image_url = (
        "https://images.unsplash.com/photo-1501785888041-af3ef285b470"
        "?auto=format&fit=crop&w=1200&q=80"
    )
    try:
        img_path = download_image(image_url)
        show_image(img_path)
        # Keep the script alive briefly so the viewer can launch before the temp file is deleted.
        time.sleep(5)
        os.remove(img_path)
    except Exception as e:
        print(f"Could not display image: {e}")

if __name__ == "__main__":
    main()
