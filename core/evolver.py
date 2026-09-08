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
            f"You are SkillClaw, an autonomous Python tool generator for Termux on Android.\n"
            f"Generate a self-contained Python script for tool: '{tool_name}'.\n"
            f"Objective: {objective}\n\n"
            "REQUIREMENTS:\n"
            "1. Entrypoint MUST be exactly: def run(**kwargs) -> dict:\n"
            "2. Must return a dict populated ONLY with data relevant to the objective. Never return an empty dict.\n"
            "3. Import all necessary standard libraries (socket, os, sys, time, shutil).\n"
            "4. Termux Android Constraints:\n"
            "   - Do NOT run binary `ip` or access `/proc/net` (they fail or are not installed).\n"
            "   - For local IP discovery, use standard socket techniques:\n"
            "     s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)\n"
            "     s.connect(('8.8.8.8', 80))\n"
            "     local_ip = s.getsockname()[0]\n"
            "     s.close()\n"
            "   - For uptime, use `time.clock_gettime(time.CLOCK_BOOTTIME)`.\n"
            "5. Output ONLY clean Python code inside ```python ``` blocks."
        )

        error_context = ""
        for attempt in range(1, max_retries + 1):
            full_prompt = base_prompt
            if error_context:
                full_prompt += f"\nCRITICAL FIX: Previous attempt failed with:\n{error_context}\nFix it according to the requirements."

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
