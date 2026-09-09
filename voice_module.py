import subprocess
import sys

def activate_voice():
    """Activates single-turn voice listening via Termux API speech-to-text."""
    print("[Vagar Voice]: Listening for voice input...")
    try:
        res = subprocess.run(
            ["termux-speech-to-text"],
            capture_output=True,
            text=True,
            timeout=15
        )
        if res.returncode == 0 and res.stdout.strip():
            spoken_text = res.stdout.strip()
            print(f"[Voice Captured]: {spoken_text}")
            return {"status": "success", "text": spoken_text}
        else:
            return {"status": "error", "message": "No speech detected or speech-to-text timed out."}
    except FileNotFoundError:
        return {"status": "error", "message": "termux-speech-to-text binary not found. Please install Termux:API app and package."}
    except Exception as e:
        return {"status": "error", "message": str(e)}

if __name__ == "__main__":
    print(activate_voice())
