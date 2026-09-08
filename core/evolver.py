import os
import importlib.util
import json
import urllib.request

class SkillEvolver:
    def __init__(self, skill_claw, tools_dir="tools", ollama_host="http://127.0.0.1:11434"):
        self.skill_claw = skill_claw
        self.tools_dir = tools_dir
        self.ollama_host = ollama_host
        os.makedirs(self.tools_dir, exist_ok=True)
        self.model_name = self._get_active_model()

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

    def generate_tool(self, tool_name: str, description: str):
        prompt = f"""Write ONLY a valid Python function named '{tool_name}' that does: {description}.
Rules:
- Return a dictionary or string.
- Wrap ALL socket operations, file reads, and service lookups (like socket.getservbyport) in try-except blocks so unknown ports or errors default cleanly to 'unknown'.
- NO markdown formatting, NO backticks, NO explanations. ONLY python code."""

        for attempt in range(3):
            try:
                req = urllib.request.Request(
                    f"{self.ollama_host}/api/generate",
                    data=json.dumps({
                        "model": self.model_name,
                        "prompt": prompt,
                        "stream": False
                    }).encode("utf-8"),
                    headers={"Content-Type": "application/json"}
                )
                with urllib.request.urlopen(req, timeout=180) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    code = data.get("response", "").strip()
                    if "```" in code:
                        parts = code.split("```")
                        for p in parts:
                            if "def " in p:
                                code = p.replace("python", "").strip()
                                break

                    file_path = os.path.join(self.tools_dir, f"{tool_name}.py")
                    with open(file_path, "w") as f:
                        f.write(code)

                    spec = importlib.util.spec_from_file_location(tool_name, file_path)
                    mod = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(mod)

                    if hasattr(mod, tool_name):
                        func = getattr(mod, tool_name)
                        self.skill_claw.register_dynamic_tool(tool_name, func)
                        print(f"[Evolver] Successfully synthesized and loaded robust tool: {tool_name}")
                        return True
            except Exception as e:
                print(f"[Evolver] Attempt {attempt + 1} failed: {e}")
        print(f"[Evolver] Failed to evolve tool '{tool_name}' after 3 attempts.")
        return False
