path = "run_vagar.py"
with open(path, "r") as f:
    lines = f.readlines()

new_lines = []
i = 0
while i < len(lines):
    if "user_input.startswith" in lines[i] and "!skill" in lines[i]:
        new_lines.append('    if user_input.startswith("!skill"):\n')
        new_lines.append('        parts = user_input[6:].strip().split(maxsplit=1)\n')
        new_lines.append('        skill_name = parts[0] if parts else ""\n')
        new_lines.append('        skill_arg = parts[1] if len(parts) > 1 else ""\n')
        new_lines.append('        if skill_name in claw.registry:\n')
        new_lines.append('            import inspect\n')
        new_lines.append('            sig = inspect.signature(claw.registry[skill_name])\n')
        new_lines.append('            if len(sig.parameters) > 0:\n')
        new_lines.append('                res = claw.execute_skill(skill_name, args=skill_arg)\n')
        new_lines.append('            else:\n')
        new_lines.append('                res = claw.execute_skill(skill_name)\n')
        new_lines.append('            print(f"[Skill Result]:\\n{res}")\n')
        new_lines.append('            try:\n')
        new_lines.append('                speak(f"Executed {skill_name}")\n')
        new_lines.append('            except:\n')
        new_lines.append('                pass\n')
        new_lines.append('        else:\n')
        new_lines.append('            print(f"[Error]: Skill \x27{skill_name}\x27 not found.")\n')
        new_lines.append('        continue\n')
        
        i += 1
        while i < len(lines) and "available =" not in lines[i] and "lowered =" not in lines[i]:
            i += 1
    else:
        new_lines.append(lines[i])
        i += 1

with open(path, "w") as f:
    f.writelines(new_lines)

import ast
try:
    ast.parse("".join(new_lines))
    print("AST verification passed successfully!")
except Exception as e:
    print(f"AST Error: {e}")
