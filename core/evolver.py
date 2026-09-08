import json
import re
import requests
from core.skillclaw import SkillClaw

class SkillEvolver:
    def __init__(self, skillclaw: SkillClaw, ollama_url: str = "http://127.0.0.1:11434", model: str = "qwen2.5-coder:1.5b"):
        self.claw = skillclaw
        self.ollama_url = f"{ollama_url}/api/generate"
        self.model = model

    def clean_code(self, raw_response: str) -> str:
        match = re.search(r"```(?:python)?(.*?)```", raw_response, re.DOTALL)
        if match:
            return match.group(1).strip()
        return raw_response.strip()

    def generate_tool(self, tool_name: str, objective: str, max_retries: int = 3) -> bool:
        base_prompt = (
            f"You are SkillClaw, a low-level Python tool developer for Vagar.\n"
            f"Write a standalone Python file for tool: '{tool_name}'.\n"
            f"Objective: {objective}\n\n"
            f"RULES:\n"
            f"1. Must define: def run(**kwargs):\n"
            f"2. Return a pure dict with all results.\n"
            f"3. Explicitly import all used standard libraries (e.g. shutil, os, sys, platform, math).\n"
            f"4. Do NOT unpack tuples directly. Access attributes directly (e.g. usage = shutil.disk_usage('/'); total = usage.total).\n"
            f"5. Output ONLY the raw python code inside ```python ``` blocks. No conversational text.\n"
        )

        error_context = ""
        for attempt in range(1, max_retries + 1):
            full_prompt = base_prompt
            if error_context:
                full_prompt += f"\nCRITICAL FIX: Previous attempt failed:\n{error_context}\nFix the imports and unpacking."

            try:
                res = requests.post(
                    self.ollama_url,
                    json={"model": self.model, "prompt": full_prompt, "stream": False},
                    timeout=60.0
                )
                if res.status_code != 200:
                    print(f"[Evolver] Ollama HTTP {res.status_code}")
                    return False

                code = self.clean_code(res.json().get("response", ""))
                success, msg = self.claw.register_tool_from_code(tool_name, code)
                if success:
                    print(f"[Evolver] Skill '{tool_name}' verified and hot-reloaded on attempt {attempt}.")
                    return True
                else:
                    print(f"[Evolver] Attempt {attempt} failed: {msg}")
                    error_context = msg

            except Exception as e:
                print(f"[Evolver] Error: {e}")
                return False

        return False
