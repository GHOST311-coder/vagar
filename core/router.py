import json
import re
import requests

class IntentRouter:
    def __init__(self, ollama_url: str = "http://127.0.0.1:11434", model: str = "qwen2.5-coder:1.5b"):
        self.endpoint = f"{ollama_url}/api/generate"
        self.model = model

    def route(self, user_prompt: str, available_skills: list) -> dict:
        prompt = (
            "You are the intent dispatcher for Vagar. Analyze the user prompt and return a single JSON object.\n\n"
            f"Available Skills in memory: {available_skills}\n\n"
            "Classification Rules:\n"
            "- If the user asks to create, build, generate, synthesize, or write a tool/skill -> skill_evolve\n"
            "- If the user asks for information covered by an Available Skill -> skill_exec\n"
            "- If the user asks to run a low-level terminal/bash command or check hardware/system info not in skills -> shell\n"
            "- If it is casual greetings or conversation -> chat\n\n"
            "Examples:\n"
            'User: "create a script to monitor cpu temp"\n'
            'JSON: {"intent": "skill_evolve", "skill_name": "cpu_temp", "objective": "monitor cpu temperature"}\n\n'
            'User: "how much disk space is left?"\n'
            'JSON: {"intent": "skill_exec", "skill_name": "disk_space"}\n\n'
            'User: "show routing table"\n'
            'JSON: {"intent": "shell", "command": "ip route"}\n\n'
            'User: "hello how are you"\n'
            'JSON: {"intent": "chat", "reply": "Online and ready."}\n\n'
            f'User: "{user_prompt}"\n'
            "JSON:"
        )

        try:
            res = requests.post(
                self.endpoint,
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "format": "json",
                    "stream": False,
                    "options": {"temperature": 0.0}
                },
                timeout=30.0
            )
            if res.status_code == 200:
                raw = res.json().get("response", "").strip()
                data = json.loads(raw)
                if isinstance(data, dict) and "intent" in data:
                    return data
        except Exception as e:
            print(f"[Router Parse Error]: {e}")

        return {"intent": "chat", "reply": "Standing by."}
