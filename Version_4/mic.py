import speech_recognition as sr

def listen_controlled():
    r = sr.Recognizer()

    # --- THE FIX ---
    # 1. Set this first to a low value
    r.non_speaking_duration = 0.3 
    
    # 2. Now set your pause threshold (must be >= 0.3)
    r.pause_threshold = 2
    
    r.energy_threshold = 300 
    r.dynamic_energy_threshold = True 

    with sr.Microphone() as source:
        # The error happened here because the logic check failed
        # print("Calibrating for 1 second...")
        r.adjust_for_ambient_noise(source, duration=1)
        
        # print(f"Current Sensitivity: {r.energy_threshold}")
        print("Listening...")

        try:
            audio = r.listen(source, timeout=None, phrase_time_limit=None)
            print("Processing...")
            text = r.recognize_google(audio)
            return text
            
        except sr.UnknownValueError:
            return ""
        except Exception as e:
            return f"Error: {e}"

if __name__ == "__main__":
    while True:
        print(f"You said: {listen_controlled()}")