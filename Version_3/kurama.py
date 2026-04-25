# kurama.py
import time
import random
from router import build_graph
from decision import decision_node
from state import KuramaState
from voice import speak, listen_once, pre_warm_tts

# ══════════════════════════════════════════════════════════════════════════════
#  SMART SPEAK
# ══════════════════════════════════════════════════════════════════════════════

def smart_speak(text: str) -> str | None:
    """
    Speak response. Returns interrupted text if user spoke during playback.
    Returns None if completed normally.
    """
    if not text or not text.strip():
        return None
    return speak(text)


# ══════════════════════════════════════════════════════════════════════════════
#  COMMAND HANDLER
# ══════════════════════════════════════════════════════════════════════════════

def handle_command(query: str) -> str | None:
    """
    Handle user command. Returns interrupted text if user
    interrupted Kurama while speaking, so main loop can
    process it immediately without listening again.
    """
    print(f"[USER]: {query}")

    tasks = decision_node(query)

    if not tasks or isinstance(tasks, str):
        speak("Sorry, I couldn't understand that.")
        return None

    print(f"[Tasks]: {tasks}")

    try:
        workflow = build_graph(tasks)

        initial_state = KuramaState(
            query          = query,
            tasks          = tasks,
            results        = {},
            merge_results  = "",
            final_response = ""
        )

        result   = workflow.invoke(initial_state)
        response = result.get('final_response', 'Done.')

    except Exception as e:
        response = "Something went wrong."
        print(f"[ERROR] {e}")

    print(f"[KURAMA]: {response}")

    # speak() returns interrupted text if user barged in
    interrupted = smart_speak(response)
    return interrupted


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    pre_warm_tts()

    print("=" * 50)
    print("         K . U . R . A . M . A")
    print("=" * 50)

    speak("KURAMA online. How can I help you?")

    pending_text = None   # holds interrupted user speech

    while True:
        try:
            # If user interrupted during last response — use that text directly
            if pending_text:
                text         = pending_text
                pending_text = None
                print(f"\n[INTERRUPT COMMAND]: {text}")
            else:
                print("\n[KURAMA] Listening...")
                text = listen_once(timeout=None, phrase_limit=15)

            if not text:
                continue

            # handle_command returns interrupted text if user spoke mid-response
            interrupted  = handle_command(text)
            pending_text = interrupted   # will be processed next loop

        except KeyboardInterrupt:
            print("\n[KURAMA] Shutting down...")
            speak("Goodbye sir.")
            break