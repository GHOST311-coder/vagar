import ast
import importlib
import sys
from pathlib import Path
from typing import Callable, Dict, Any, Tuple

class SkillClaw:
    def __init__(self, tools_dir: str = "tools"):
        self.tools_path = Path(tools_dir)
        self.tools_path.mkdir(exist_ok=True)
        self.registry: Dict[str, Callable] = {}

    def validate_syntax(self, code_str: str) -> Tuple[bool, str]:
        try:
            ast.parse(code_str)
            return True, "Syntax valid"
        except SyntaxError as e:
            return False, f"AST Syntax Error at line {e.lineno}: {e.msg}"

    def register_tool_from_code(self, tool_name: str, code_str: str) -> Tuple[bool, str]:
        is_valid, message = self.validate_syntax(code_str)
        if not is_valid:
            return False, message

        tool_file = self.tools_path / f"{tool_name}.py"
        tool_file.write_text(code_str)

        module_name = f"tools.{tool_name}"
        try:
            if module_name in sys.modules:
                module = importlib.reload(sys.modules[module_name])
            else:
                module = importlib.import_module(module_name)

            if not (hasattr(module, "run") and callable(module.run)):
                return False, "Module missing mandatory callable entrypoint: 'run(**kwargs)'"

            test_run = module.run()
            if not isinstance(test_run, dict):
                return False, f"run() must return dict, got {type(test_run).__name__}"
            if len(test_run) == 0:
                return False, "Dry-run returned empty dictionary {}. Must populate valid result keys."
            if "error" in test_run:
                return False, f"Dry-run caught runtime failure: {test_run.get('error')}"

            self.registry[tool_name] = module.run
            return True, f"Skill '{tool_name}' verified and hot-reloaded."

        except Exception as e:
            if tool_file.exists():
                tool_file.unlink()
            return False, f"Runtime dry-run failed: {type(e).__name__} - {str(e)}"

    async def execute_skill(self, tool_name: str, **kwargs) -> Any:
        if tool_name not in self.registry:
            raise KeyError(f"Skill '{tool_name}' not loaded in registry.")
        return self.registry[tool_name](**kwargs)
