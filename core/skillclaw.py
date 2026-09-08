import ast
import importlib.util
from pathlib import Path
from typing import Dict, Any, Tuple

class SkillClaw:
    def __init__(self, tools_dir: str = "tools"):
        self.tools_path = Path(tools_dir).resolve()
        self.tools_path.mkdir(exist_ok=True)
        self.registry: Dict[str, Any] = {}
        self.load_existing_tools()

    def load_existing_tools(self) -> None:
        for py_file in self.tools_path.glob("*.py"):
            if py_file.name.startswith("__"):
                continue
            skill_name = py_file.stem
            try:
                spec = importlib.util.spec_from_file_location(skill_name, py_file)
                if spec and spec.loader:
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    if hasattr(module, "run") and callable(module.run):
                        self.registry[skill_name] = module.run
            except Exception as e:
                print(f"[SkillClaw] Failed to preload {skill_name}: {e}")

    def validate_ast(self, code_str: str) -> Tuple[bool, str]:
        try:
            tree = ast.parse(code_str)
            has_run = any(
                isinstance(node, ast.FunctionDef) and node.name == "run"
                for node in ast.walk(tree)
            )
            if not has_run:
                return False, "Validation error: Missing 'def run(**kwargs):' entrypoint function."
            return True, ""
        except SyntaxError as e:
            return False, f"SyntaxError during AST check: {e}"

    def register_tool_from_code(self, tool_name: str, code_str: str) -> Tuple[bool, str]:
        valid, err = self.validate_ast(code_str)
        if not valid:
            return False, err

        file_path = self.tools_path / f"{tool_name}.py"
        try:
            file_path.write_text(code_str)
            spec = importlib.util.spec_from_file_location(tool_name, file_path)
            if not spec or not spec.loader:
                return False, "Failed to build module spec"

            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            if not hasattr(module, "run") or not callable(module.run):
                return False, "Module lacks callable run() function"

            dry_run = module.run()
            if not isinstance(dry_run, dict) or not dry_run:
                return False, "Runtime dry-run failed: run() must return a non-empty dict."

            self.registry[tool_name] = module.run
            return True, ""
        except Exception as e:
            if file_path.exists():
                file_path.unlink(missing_ok=True)
            return False, f"Runtime dry-run failed: {type(e).__name__} - {e}"

    def execute_skill(self, tool_name: str, **kwargs) -> Dict[str, Any]:
        if tool_name not in self.registry:
            raise KeyError(f"Skill '{tool_name}' not registered.")
        return self.registry[tool_name](**kwargs)
