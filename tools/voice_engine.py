import subprocess
import json
import shutil

def speak(text: str, pitch: float = 1.0, rate: float = 1.0):
    if not shutil.which("termux-tts-speak"):
        return {"status": "error", "message": "termux-tts-speak not found"}
    try:
        subprocess.run(
            ["termux-tts-speak", "-p", str(pitch), "-r", str(rate), text],
            check=True,
            timeout=15
        )
        return {"status": "success", "spoken": text}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def listen():
    if not shutil.which("termux-speech-to-text"):
        return {"status": "error", "message": "termux-speech-to-text not found"}
    try:
        proc = subprocess.run(
            ["termux-speech-to-text"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=15
        )
        output = proc.stdout.strip()
        if output:
            try:
                parsed = json.loads(output)
                if isinstance(parsed, dict) and "text" in parsed:
                    return {"status": "success", "transcript": parsed["text"]}
            except json.JSONDecodeError:
                return {"status": "success", "transcript": output}
        return {"status": "silent", "transcript": ""}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def run(action="listen", text="System operational", **kwargs):
    if action == "speak":
        return speak(text)
    return listen()
