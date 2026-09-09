import subprocess

def clipboard_manager(action="get", text=""):
    """Manages clipboard text interactions via Termux API."""
    try:
        if action == "set" and text:
            res = subprocess.run(["termux-clipboard-set", text], capture_output=True, text=True, timeout=3)
            return {"status": "success", "message": "Clipboard updated successfully"}
        else:
            res = subprocess.run(["termux-clipboard-get"], capture_output=True, text=True, timeout=3)
            return {"status": "success", "clipboard": res.stdout.strip()}
    except Exception as e:
        return {"status": "error", "message": str(e)}

if __name__ == "__main__":
    print(clipboard_manager())
