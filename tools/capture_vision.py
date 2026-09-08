import subprocess
import os
import base64
import json
import urllib.request

def _get_active_model():
    try:
        req = urllib.request.Request("http://127.0.0.1:11434/api/tags")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            models = data.get("models", [])
            if models:
                return models[0].get("name", "llama3:latest")
    except Exception:
        pass
    return "llama3:latest"

def capture_vision(prompt_text: str = "Describe what you see in this image."):
    """Captures a frame and sends it to the active local model for vision analysis."""
    try:
        os.makedirs("tools", exist_ok=True)
        img_path = "tools/latest_capture.jpg"
        if os.path.exists(img_path):
            os.remove(img_path)
            
        result = subprocess.run(["termux-camera-photo", img_path], capture_output=True, text=True, timeout=10)
        
        if not os.path.exists(img_path) or os.path.getsize(img_path) == 0:
            return {"status": "error", "message": f"Camera capture failed: {result.stderr}"}
            
        with open(img_path, "rb") as f:
            img_base64 = base64.b64encode(f.read()).decode("utf-8")
            
        active_model = _get_active_model()
        req_data = {
            "model": active_model,
            "prompt": prompt_text,
            "images": [img_base64],
            "stream": False
        }
        
        req = urllib.request.Request(
            "http://127.0.0.1:11434/api/generate",
            data=json.dumps(req_data).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return {
                "status": "success",
                "model_used": active_model,
                "description": data.get("response", "No response from model.")
            }
    except Exception as e:
        return {"status": "error", "message": str(e)}
