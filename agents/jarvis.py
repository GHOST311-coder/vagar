import json
import urllib.request

class JarvisCognition:
    """Handles core cognitive reasoning via local Ollama instance."""
    def __init__(self, ollama_host="http://127.0.0.1:11434"):
        self.ollama_host = ollama_host
        self.model_name = self._get_active_model()

    def _get_active_model(self):
        try:
            req = urllib.request.Request(f"{self.ollama_host}/api/tags")
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                models = data.get("models", [])
                if models:
                    return models[0].get("name", "llama3:latest")
        except Exception:
            pass
        return "llama3:latest"

    def query_local_brain(self, prompt_text: str) -> str:
        try:
            req = urllib.request.Request(
                f"{self.ollama_host}/api/generate",
                data=json.dumps({
                    "model": self.model_name,
                    "prompt": prompt_text,
                    "stream": False
                }).encode("utf-8"),
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data.get("response", "").strip()
        except Exception as e:
            return f"Brain error: {e}"
