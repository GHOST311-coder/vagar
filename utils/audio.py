import subprocess

def speak(text: str):
    """Speaks text aloud using Termux text-to-speech engine."""
    try:
        if not text:
            return
        clean_text = text.replace('"', '').replace("'", "")
        subprocess.Popen(["termux-tts-speak", clean_text], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass
