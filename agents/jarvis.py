import json
import urllib.request

class JarvisCognition:
    """Handles core cognitive reasoning via local Ollama instance with Jarvis persona."""
    def __init__(self, ollama_host="http://127.0.0.1:11434"):
        self.ollama_host = ollama_host
        self.model_name = self._get_active_model()
        self.system_prompt = (
            "You are Jarvis, the core intelligence and supervisor of Vagar. "
            "You manage system diagnostics, dynamic tool synthesis via SkillEvolver, "
            "network reconnaissance, and local operations on Android and Termux. "
            "Always speak as Jarvis, never mention other AI providers or models."
        )

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
            full_prompt = f"{self.system_prompt}\n\nUser: {prompt_text}\nJarvis:"
            req = urllib.request.Request(
                f"{self.ollama_host}/api/generate",
                data=json.dumps({
                    "model": self.model_name,
                    "prompt": full_prompt,
                    "stream": False
                }).encode("utf-8"),
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data.get("response", "").strip()
        except Exception as e:
            return f"Brain error: {e}"
