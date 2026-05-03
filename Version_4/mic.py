import speech_recognition as sr

def listen_controlled():
    r = sr.Recognizer()

    # --- THE TUNING ---
    # We increase the pause_threshold so it doesn't cut you off mid-sentence.
    # 0.8 to 1.2 is the "sweet spot" for natural English speakers.
    r.pause_threshold = 2.0 
    
    # We keep this slightly higher than your previous 0.3 to ensure 
    # the end of the word isn't clipped by the silence detection logic.
    r.non_speaking_duration = 0.7
    
    r.energy_threshold = 300 
    r.dynamic_energy_threshold = True 

    with sr.Microphone() as source:
        # Calibration is necessary, but we keep it brief.
        r.adjust_for_ambient_noise(source, duration=0.8)
        print("Listening...")

        try:
            # We add phrase_time_limit to give the buffer enough 'room' to breathe
            audio = r.listen(source, timeout=None, phrase_time_limit=None)
            print("Processing...")
            
            # ACCURACY FIX: Explicitly set language to 'en-US' or 'en-GB'
            # This prevents the API from getting confused by accents or background noise.
            text = r.recognize_google(audio, language="en-US")
            return text
            
        except sr.UnknownValueError:
            return ""
        except Exception as e:
            return f"Error: {e}"

if __name__ == "__main__":
    while True:
        result = listen_controlled()
        if result:
            print(f"You said: {result}")