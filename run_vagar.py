import asyncio
import sys
from core.supervisor import VagarSupervisor
from agents.ultron import UltronWorker
from core.skillclaw import SkillClaw
from core.evolver import SkillEvolver

BANNER = """
=============================================
         VAGAR AUTONOMOUS SUPERVISOR
 Commands:
   !cmd <bash>        -> Execute shell via Ultron
   !skill <name> <obj>-> Synthesize/Run SkillClaw
   !list              -> View loaded skills
   exit / quit        -> Terminate engine
=============================================
"""

async def handle_input(line: str, supervisor: VagarSupervisor, claw: SkillClaw, evolver: SkillEvolver):
    line = line.strip()
    if not line:
        return

    # Direct Ultron Shell Execution
    if line.startswith("!cmd "):
        cmd = line[5:].strip()
        print(f"\n[Jarvis -> Ultron] Running: {cmd}")
        res = await supervisor.dispatch(cmd, agent="ultron")
        if res.get("stdout"):
            print(f"[Stdout]:\n{res['stdout']}")
        if res.get("stderr"):
            print(f"[Stderr]:\n{res['stderr']}")
        print(f"[Exit Code]: {res['exit_code']}\n")

    # SkillClaw Synthesis or Invocation
    elif line.startswith("!skill "):
        parts = line[7:].strip().split(" ", 1)
        tool_name = parts[0]
        objective = parts[1] if len(parts) > 1 else "Execute tool"

        if tool_name not in claw.registry:
            print(f"\n[Supervisor] '{tool_name}' not loaded. Triggering SkillClaw...")
            created = evolver.generate_tool(tool_name, objective)
            if not created:
                print(f"[Error] Skill evolution failed for {tool_name}\n")
                return

        print(f"\n[Jarvis] Executing skill '{tool_name}'...")
        try:
            output = await claw.execute_skill(tool_name)
            print(f"[Skill Result]:\n{output}\n")
        except Exception as e:
            print(f"[Execution Error]: {str(e)}\n")

    # List loaded dynamic modules
    elif line == "!list":
        print(f"\n[Loaded Skills in Memory]: {list(claw.registry.keys())}\n")

    else:
        print("[Jarvis] Unrecognized command. Use !cmd, !skill, or !list.")

async def main():
    print(BANNER)
    supervisor = VagarSupervisor()
    ultron = UltronWorker(supervisor)
    claw = SkillClaw()
    evolver = SkillEvolver(claw, ollama_url="http://127.0.0.1:11434", model="qwen2.5-coder:1.5b")

    # Pre-register any previously generated tools on startup
    for file in claw.tools_path.glob("*.py"):
        if file.name != "__init__.py":
            name = file.stem
            claw.register_tool_from_code(name, file.read_text())

    worker_task = asyncio.create_task(ultron.run_worker_loop())

    try:
        while True:
            # Readline in background thread so async queues never block
            user_input = await asyncio.to_thread(input, "vagar> ")
            if user_input.strip().lower() in ["exit", "quit"]:
                break
            await handle_input(user_input, supervisor, claw, evolver)
    finally:
        worker_task.cancel()
        print("\n[Vagar] Supervisor shut down.")

if __name__ == "__main__":
    asyncio.run(main())
