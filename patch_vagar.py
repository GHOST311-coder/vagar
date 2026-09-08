path = "run_vagar.py"
with open(path, "r") as f:
    lines = f.readlines()

new_lines = []
for line in lines:
    if line.strip().startswith('if user_input.startswith("!skill "):'):
        indent = line[:line.index("if")]
        new_lines.append(f'{indent}if user_input.startswith("!skill"):\n')
        new_lines.append(f'{indent}    parts = user_input[6:].strip().split(maxsplit=1)\n')
        new_lines.append(f'{indent}    skill_name = parts[0] if parts else ""\n')
        new_lines.append(f'{indent}    skill_arg = parts[1] if len(parts) > 1 else ""\n')
        new_lines.append(f'{indent}    if skill_name in claw.registry:\n')
        new_lines.append(f'{indent}        import inspect\n')
        new_lines.append(f'{indent}        sig = inspect.signature(claw.registry[skill_name])\n')
        new_lines.append(f'{indent}        if len(sig.parameters) > 0:\n')
        new_lines.append(f'{indent}            res = claw.execute_skill(skill_name, args=skill_arg)\n')
        new_lines.append(f'{indent}        else:\n')
        new_lines.append(f'{indent}            res = claw.execute_skill(skill_name)\n')
        new_lines.append(f'{indent}        print(f"[Skill Result]:\\n{{res}}")\n')
        new_lines.append(f'{indent}        try:\n')
        new_lines.append(f'{indent}            speak(f"Executed {{skill_name}}")\n')
        new_lines.append(f'{indent}        except Exception:\n')
        new_lines.append(f'{indent}            pass\n')
        new_lines.append(f'{indent}    else:\n')
        new_lines.append(f'{indent}        print(f"[Error]: Skill \x27{{skill_name}}\x27 not found.")\n')
        new_lines.append(f'{indent}    continue\n')
    elif 'res = claw.execute_skill(skill_name)' in line or 'skill_name = user_input.split' in line:
        continue
    else:
        new_lines.append(line)

with open(path, "w") as f:
    f.writelines(new_lines)
print("Clean patch applied successfully!")
