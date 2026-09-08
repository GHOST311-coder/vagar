import json
import requests
from typing import Dict, Any, List

class IntentRouter:
    def __init__(self, ollama_url: str = "http://127.0.0.1:11434", model: str = "qwen2.5-coder:1.5b"):
        self.ollama_url = f"{ollama_url}/api/generate"
        self.model = model

    def route(self, user_input: str, available_skills: List[str] = None, history_context: str = "") -> Dict[str, Any]:
        skills_str = ", ".join(available_skills) if available_skills else "none"

        prompt = (
            f"You are the intent router and brain for Vagar on Android Termux.\n"
            f"Registered skills: [{skills_str}]\n\n"
            f"Recent Command/Tool History:\n{history_context}\n\n"
            f"User input: \"{user_input}\"\n\n"
            f"Choose ONE intent type:\n"
            f"1. 'skill_exec': If the query asks to run a registered skill.\n"
            f"2. 'skill_evolve': If the user asks to build/create/synthesize a new tool.\n"
            f"3. 'answer': If the user is asking a conversational question or asking about the previous output.\n"
            f"4. 'shell_exec': If the input is a raw terminal command to execute.\n\n"
            f"Respond ONLY in valid JSON:\n"
            f'{{"intent": "skill_exec"|"skill_evolve"|"answer"|"shell_exec", "target": "<skill or command>", "response": "<conversational answer if intent is answer>"}}'
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
