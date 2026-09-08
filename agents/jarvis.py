import json
import urllib.request
import urllib.error

class JarvisCognition:
    """Jarvis: Intent analysis, cognitive synthesis, and high-level conversational routing."""
    def __init__(self, model_name: str = "llama3:latest", ollama_host: str = "http://127.0.0.1:11434"):
        self.model_name = model_name
        self.ollama_host = ollama_host

    def query_local_brain(self, prompt: str) -> str:
        system_instruction = (
            "You are Jarvis, the cognitive supervisor of the Vagar OS architecture on Android Termux. "
            "Coordinate Ultron for execution and Hermes for messaging. Keep answers concise, factual, and actionable."
        )
        try:
            req = urllib.request.Request(
                f"{self.ollama_host}/api/generate",
                data=json.dumps({
                    "model": self.model_name,
                    "prompt": prompt,
                    "system": system_instruction,
                    "stream": False
                }).encode("utf-8"),
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data.get("response", "").strip()
        except Exception:
            return None

    def route_intent(self, user_input: str, router, available_skills: list, history: str):
        decision = router.route(user_input, available_skills=available_skills, history_context=history)
        intent = decision.get("intent", "shell_exec")

        if intent == "answer":
            local_inference = self.query_local_brain(user_input)
            if local_inference:
                decision["response"] = local_inference
        return decision
