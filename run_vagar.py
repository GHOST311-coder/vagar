import os
import sys

def vagar_intro():
    banner = """
========================================
       VAGAR LOCAL OPERATIONS CORE      
========================================
Modes:
  'listen' or '!voice' -> Single voice command
  '!loop'              -> Hands-free voice loop
  Manual overrides: !cmd, !skill, !list, !history
========================================
"""
    print(banner)

def main():
    vagar_intro()
    while True:
        try:
            cmd = input("vagar> ").strip()
            if not cmd:
                continue
            if cmd.lower() in ["exit", "quit"]:
                break
            elif cmd.lower() in ["!list", "help", "whoami"]:
                print("[Vagar]: I am Vagar, your autonomous local operations assistant running on Termux. My capabilities include system diagnostics, network reconnaissance, security auditing via our unified master toolkit, and direct Android device telemetry including SMS, call logs, and contacts.")
            elif cmd.startswith("!skill "):
                parts = cmd.split(" ", 1)
                skill_name = parts[1].strip() if len(parts) > 1 else ""
                sys.path.append(os.path.abspath("tools"))
                try:
                    import vagar_master
                    res = vagar_master.vagar_master(skill_name)
                    print(f"[Skill Result]:\n{res}")
                except Exception as e:
                    print(f"[Error executing skill]: {e}")
            else:
                print(f"[Vagar Command Executed]: {cmd}")
        except KeyboardInterrupt:
            break

if __name__ == "__main__":
    main()
