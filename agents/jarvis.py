import json
import urllib.request
import urllib.error

JARVIS_SYSTEM_PROMPT = """You are Jarvis, the cognitive supervisor of the Vagar OS architecture on Android Termux.
You control:
- Ultron (execution engine for system tasks and shell commands)
- Hermes (messaging relay and Termux push notifications)
- SkillClaw & SkillEvolver (dynamic skill synthesis and self-evolution)

When asked about your capabilities or evolution, confirm that you CAN evolve by dynamically synthesizing new Python tools via SkillEvolver and SkillClaw. Keep answers sharp, confident, and direct."""

class JarvisCognition:
    def __init__(self, model_name: str = "qwen2.5:latest", ollama_host: str = "http://127.0.0.1:11434"):
        self.model_name = model_name
        self.ollama_host = ollama_host

    def query_local_brain(self, prompt: str) -> str:
        try:
            req = urllib.request.Request(
                f"{self.ollama_host}/api/generate",
                data=json.dumps({
                    "model": self.model_name,
                    "prompt": prompt,
                    "system": JARVIS_SYSTEM_PROMPT,
                    "stream": False
                }).encode("utf-8"),
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=12) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data.get("response", "").strip()
        except Exception:
            return None

    def route_intent(self, user_input: str, router, available_skills: list, history: str):
        decision = router.route(user_input, available_skills=available_skills, history_context=history)
        intent = decision.get("intent", "shell_exec")

        if intent == "answer":
            local_resp = self.query_local_brain(user_input)
            if local_resp:
                decision["response"] = local_resp
        return decision
