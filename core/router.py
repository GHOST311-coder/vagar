import json
import re
import requests
from typing import Dict, Any, List

class IntentRouter:
    def __init__(self, ollama_url: str = "http://127.0.0.1:11434", model: str = "qwen2.5-coder:1.5b"):
        self.ollama_url = f"{ollama_url}/api/generate"
        self.model = model

    def route(self, user_input: str, available_skills: List[str] = None) -> Dict[str, Any]:
        skills_str = ", ".join(available_skills) if available_skills else "none"
        
        prompt = (
            f"You are the intent router for Vagar on Android Termux.\n"
            f"Currently registered skills: [{skills_str}]\n\n"
            f"Determine the intent of: \"{user_input}\"\n"
            f"Choose ONE intent type:\n"
            f"1. 'skill_exec': If the query asks for information that matches one of the registered skills.\n"
            f"2. 'skill_evolve': If the user explicitly asks to create, build, or synthesize a new tool.\n"
            f"3. 'shell_exec': If the input is a direct terminal command or general task.\n\n"
            f"Respond ONLY in valid JSON with no markdown:\n"
            f'{{"intent": "skill_exec"|"skill_evolve"|"shell_exec", "target": "<skill_name or command>", "objective": "<description>"}}'
        )

        try:
            res = requests.post(
                self.ollama_url,
                json={"model": self.model, "prompt": prompt, "stream": False, "format": "json"},
                timeout=30.0
            )
            if res.status_code == 200:
                return json.loads(res.json().get("response", "{}"))
        except Exception:
            pass

        return {"intent": "shell_exec", "target": user_input}
