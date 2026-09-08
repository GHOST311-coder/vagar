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
            f"You are SkillClaw, an autonomous Python tool generator tailored for Android Termux userland.\n"
            f"Create a standalone Python tool: '{tool_name}'.\n"
            f"Objective: {objective}\n\n"
            f"ENVIRONMENT CONSTRAINTS (Android / Termux):\n"
            f"1. Entrypoint MUST be: def run(**kwargs):\n"
            f"2. Return a populated dict containing results. Never return an empty dict.\n"
            f"3. Must NOT access restricted SELinux paths (e.g., /proc/uptime, /proc/kmsg, /sys/class/power_supply) which fail with Errno 13.\n"
            f"4. For system uptime on Android, ALWAYS use: `time.clock_gettime(time.CLOCK_BOOTTIME) / 3600` or `time.monotonic() / 3600`.\n"
            f"5. For storage, use `shutil.disk_usage('/data/data/com.termux/files/home')`.\n"
            f"6. Always explicitly import required standard modules (time, os, shutil, sys).\n"
            f"7. Output ONLY clean Python code inside ```python ``` blocks.\n"
        )

        error_context = ""
        for attempt in range(1, max_retries + 1):
            full_prompt = base_prompt
            if error_context:
                full_prompt += f"\nCRITICAL: Previous attempt failed with this error:\n{error_context}\nFix it according to the Android Termux constraints."

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
