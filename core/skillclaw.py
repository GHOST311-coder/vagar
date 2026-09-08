import os
import importlib.util

class SkillClaw:
    """Manages the registration, execution, and hot-loading of diagnostic and security tools."""
    def __init__(self, tools_dir="tools"):
        self.tools_dir = tools_dir
        self.registry = {}
        self.load_builtins()

    def register_dynamic_tool(self, name, func):
        self.registry[name] = func

    def load_builtins(self):
        if not os.path.exists(self.tools_dir):
            os.makedirs(self.tools_dir, exist_ok=True)
            return
        
        for filename in os.listdir(self.tools_dir):
            if filename.endswith(".py") and not filename.startswith("__"):
                mod_name = filename[:-3]
                file_path = os.path.join(self.tools_dir, filename)
                try:
                    spec = importlib.util.spec_from_file_location(mod_name, file_path)
                    mod = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(mod)
                    for attr in dir(mod):
                        if not attr.startswith("_"):
                            func = getattr(mod, attr)
                            if callable(func):
                                self.registry[attr] = func
                except Exception as e:
                    print(f"[SkillClaw] Error loading {filename}: {e}")

    def execute_skill(self, skill_name, *args, **kwargs):
        if skill_name in self.registry:
            try:
                return self.registry[skill_name](*args, **kwargs)
            except Exception as e:
                return {"status": "error", "message": str(e)}
        return {"status": "error", "message": f"Skill '{skill_name}' not registered."}
