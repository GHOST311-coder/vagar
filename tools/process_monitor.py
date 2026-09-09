import subprocess

def process_monitor():
    """Retrieves top CPU and memory consuming processes."""
    try:
        res = subprocess.run(["ps", "-ef"], capture_output=True, text=True, timeout=5)
        if res.returncode == 0:
            lines = res.stdout.strip().split("\n")
            top_lines = lines[:10]  # Header + top 9 processes
            return {"status": "success", "processes": top_lines}
        return {"status": "error", "message": "Failed to list processes"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

if __name__ == "__main__":
    print(process_monitor())
