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
        code = match.group(1).strip() if match else raw_response.strip()

        preamble = (
            "import os\n"
            "import sys\n"
            "import time\n"
            "import socket\n"
            "import shutil\n"
            "import subprocess\n"
            "import re\n"
        )
        if not code.startswith("import"):
            code = preamble + "\n" + code
        return code

    def generate_tool(self, tool_name: str, objective: str, max_retries: int = 3) -> bool:
        base_prompt = (
            f"You are SkillClaw for Android Termux.\n"
            f"Write a standalone Python script for tool: '{tool_name}'.\n"
            f"Objective: {objective}\n\n"
            "REQUIREMENTS:\n"
            "1. Entrypoint: def run(**kwargs) -> dict:\n"
            "2. Return a dict with actual calculated values. Never return an empty dict.\n"
            "3. For RAM/Memory on Android, parse `/proc/meminfo`.\n"
            "4. For Uptime, use `time.clock_gettime(time.CLOCK_BOOTTIME)`.\n"
            "5. For Local IP, use standard UDP socket connection to 8.8.8.8:80.\n"
            "6. Output ONLY executable python code in ```python ``` blocks."
        )

        error_context = ""
        for attempt in range(1, max_retries + 1):
            full_prompt = base_prompt
            if error_context:
                full_prompt += f"\nCRITICAL FIX: Previous attempt failed:\n{error_context}\nFix it."

            try:
                res = requests.post(
                    self.ollama_url,
                    json={"model": self.model, "prompt": full_prompt, "stream": False},
                    timeout=60.0
                )
                if res.status_code != 200:
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
