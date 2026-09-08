import os
import importlib.util
import json
import urllib.request

class SkillEvolver:
    """Dynamically synthesizes new Python tool modules, runs validation dry-runs, and hot-loads them into SkillClaw."""
    def __init__(self, skill_claw, tools_dir="tools", model_name="qwen2.5:latest", ollama_host="http://127.0.0.1:11434"):
        self.skill_claw = skill_claw
        self.tools_dir = tools_dir
        self.model_name = model_name
        self.ollama_host = ollama_host
        os.makedirs(self.tools_dir, exist_ok=True)

    def generate_tool(self, tool_name: str, description: str):
        prompt = f"""Write a Python function named '{tool_name}' that performs the following task: {description}.
Requirements:
- Return the result as a dictionary or string.
- Handle all exceptions (like FileNotFoundError, socket errors, etc.) gracefully inside the function and return a dictionary with error info if something fails.
- Do NOT include any markdown formatting blocks like ```python or ```. Output ONLY raw executable Python code.
- Ensure all string parsing uses safe methods (e.g., stripping units like 'kB' or checking list lengths before indexing)."""

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
                    if code.startswith("```"):
                        code = code.split("\n", 1)[1]
                    if code.endswith("```"):
                        code = code.rsplit("\n", 1)[0]
                    code = code.strip()

                    file_path = os.path.join(self.tools_dir, f"{tool_name}.py")
                    with open(file_path, "w") as f:
                        f.write(code)

                    # Dry run validation
                    spec = importlib.util.spec_from_file_location(tool_name, file_path)
                    mod = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(mod)

                    if hasattr(mod, tool_name):
                        func = getattr(mod, tool_name)
                        # Quick sanity check execution
                        func()
                        self.skill_claw.register_dynamic_tool(tool_name, func)
                        print(f"[Evolver] Successfully synthesized and loaded tool: {tool_name}")
                        return True
            except Exception as e:
                print(f"[Evolver] Attempt {attempt + 1} failed: {e}")
        print(f"[Evolver] Failed to evolve tool '{tool_name}' after 3 attempts.")
        return False
