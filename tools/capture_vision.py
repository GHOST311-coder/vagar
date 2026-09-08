import subprocess
import os

def capture_vision(prompt_text: str = "Describe what you see in this image."):
    """Captures a frame and stores it locally for inspection."""
    try:
        os.makedirs("tools", exist_ok=True)
        img_path = "tools/latest_capture.jpg"
        if os.path.exists(img_path):
            os.remove(img_path)
            
        result = subprocess.run(["termux-camera-photo", img_path], capture_output=True, text=True, timeout=10)
        
        if not os.path.exists(img_path) or os.path.getsize(img_path) == 0:
            return {"status": "error", "message": f"Camera capture failed: {result.stderr}"}
            
        return {
            "status": "success",
            "image_path": img_path,
            "message": "Frame captured successfully and stored at tools/latest_capture.jpg."
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}
