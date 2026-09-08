import asyncio
from core.supervisor import VagarSupervisor
from agents.ultron import UltronWorker
from core.skillclaw import SkillClaw
from core.evolver import SkillEvolver
from core.router import IntentRouter

BANNER = """
=============================================
         VAGAR INTENT SUPERVISOR
 Speak/Type naturally in plain English:
   - "How much RAM is free?"
   - "What is my battery level?"
   - "Create a tool to calculate uptime in hours"
 Manual overrides: !cmd, !skill, !list, exit
=============================================
"""

async def process_intent(prompt: str, router: IntentRouter, supervisor: VagarSupervisor, claw: SkillClaw, evolver: SkillEvolver):
    known_skills = list(claw.registry.keys())
    decision = router.route(prompt, known_skills)
    intent = decision.get("intent", "chat")

    if intent == "shell":
        cmd = decision.get("command", "")
        print(f"\n[Jarvis -> Ultron Executing]: {cmd}")
        res = await supervisor.dispatch(cmd, agent="ultron")
        out = res.get("stdout") or res.get("stderr") or "Execution complete."
        print(f"[Ultron Output]:\n{out}\n")

    elif intent == "skill_exec":
        name = decision.get("skill_name", "")
        # Resilient fallback: if skill is missing, redirect to evolver instead of crashing
        if name not in claw.registry:
            print(f"\n[Supervisor] Skill '{name}' not in registry. Redirecting to SkillClaw...")
            created = evolver.generate_tool(name, prompt)
            if created:
                output = await claw.execute_skill(name)
                print(f"[Skill Result]:\n{output}\n")
            else:
                print(f"[Error] Failed to evolve skill '{name}'\n")
        else:
            print(f"\n[Jarvis Invoking Skill]: {name}")
            output = await claw.execute_skill(name)
            print(f"[Skill Result]:\n{output}\n")

    elif intent == "skill_evolve":
        name = decision.get("skill_name", "custom_task")
        obj = decision.get("objective", prompt)
        print(f"\n[Supervisor] Evolving new skill '{name}' via SkillClaw...")
        created = evolver.generate_tool(name, obj)
        if created:
            output = await claw.execute_skill(name)
            print(f"[Skill Result]:\n{output}\n")
        else:
            print(f"[Error] Failed to evolve skill '{name}'\n")

    else:
        print(f"\n[Jarvis]: {decision.get('reply', 'Acknowledged.')}\n")

async def main():
    print(BANNER)
    supervisor = VagarSupervisor()
    ultron = UltronWorker(supervisor)
    claw = SkillClaw()
    evolver = SkillEvolver(claw, ollama_url="http://127.0.0.1:11434", model="qwen2.5-coder:1.5b")
    router = IntentRouter(ollama_url="http://127.0.0.1:11434", model="qwen2.5-coder:1.5b")

    for file in claw.tools_path.glob("*.py"):
        if file.name != "__init__.py":
            claw.register_tool_from_code(file.stem, file.read_text())

    worker_task = asyncio.create_task(ultron.run_worker_loop())

    try:
        while True:
            user_input = await asyncio.to_thread(input, "vagar> ")
            raw = user_input.strip()
            if not raw:
                continue
            if raw.lower() in ["exit", "quit"]:
                break
            if raw == "!list":
                print(f"\n[Loaded Skills]: {list(claw.registry.keys())}\n")
                continue

            await process_intent(raw, router, supervisor, claw, evolver)
    finally:
        worker_task.cancel()
        print("\n[Vagar] Supervisor offline.")

if __name__ == "__main__":
    asyncio.run(main())
