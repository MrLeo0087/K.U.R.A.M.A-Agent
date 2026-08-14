from general_tools import GeneralAgent
from voice_control import VoiceController
agent = GeneralAgent()
voice = VoiceController()
print("==================================================")
print("      KURAMA / JARVIS VOICE ASSISTANT ONLINE      ")
print("==================================================")
print("Modes: Type 'v' for voice input, or type command directly.")
print("Type 'exit' or 'quit' to stop.\n")
while True:
    try:
        mode = input("Enter command (or press Enter for Voice Mode) : ").strip()
        if mode.lower() in ["exit", "quit"]:
            voice.speak("Shutting down system. Goodbye!")
            break
        # If user presses Enter or types 'v', trigger Microphone input
        if mode == "" or mode.lower() == "v":
            user_input = voice.listen()
            if not user_input:
                print("-" * 50)
                continue
        else:
            user_input = mode
        # Process command with LangChain / Groq Agent
        response = agent.process_command(user_input)
        print(response)
        # Speak out the response if available
        if response:
            voice.speak(str(response))
        print("-" * 50)
    except KeyboardInterrupt:
        print("\nExiting Jarvis...")
        break   