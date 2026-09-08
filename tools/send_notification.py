import subprocess
import shutil

def run(**kwargs):
    title = kwargs.get("title", "Vagar Alert")
    message = kwargs.get("message", "Task completed successfully.")
    
    if not shutil.which("termux-notification"):
        return {"status": "error", "message": "termux-notification binary not found. Install termux-api."}

    cmd = ["termux-notification", "--title", str(title), "--content", str(message)]
    try:
        subprocess.run(cmd, check=True, timeout=5)
        return {"status": "success", "title": title, "content": message}
    except Exception as e:
        return {"status": "error", "error": str(e)}
