import asyncio
import sys
from core.supervisor import VagarSupervisor
from agents.ultron import UltronWorker
from core.skillclaw import SkillClaw
from core.evolver import SkillEvolver
from core.router import IntentRouter

async def main():
    supervisor = VagarSupervisor()
    worker = UltronWorker(supervisor)
    claw = SkillClaw()
    evolver = SkillEvolver(claw)
    router = IntentRouter()

    asyncio.create_task(worker.run_worker_loop())

    print("==================================================")
    print("             VAGAR INTENT SUPERVISOR              ")
    print(" Speak/Type naturally in plain English:          ")
    print("   - 'How much RAM is free?'                      ")
    print("   - 'What is my network IP?'                     ")
    print("   - 'Create a tool to calculate uptime in hours' ")
    print(" Manual overrides: !cmd, !skill, !list, exit      ")
    print("==================================================")

    while True:
        try:
            user_input = await asyncio.to_thread(input, "\nvagar> ")
            user_input = user_input.strip()
            if not user_input:
                continue

            if user_input.lower() in ["exit", "quit"]:
                print("[Vagar] Supervisor offline.")
                sys.exit(0)

            if user_input == "!list":
                print(f"[Skills Available]: {list(claw.registry.keys())}")
                continue

            if user_input.startswith("!skill "):
                skill_name = user_input.split(" ", 1)[1].strip()
                if skill_name in claw.registry:
                    res = claw.execute_skill(skill_name)
                    print(f"[Skill Result]:\n{res}")
                else:
                    print(f"[Error]: Skill '{skill_name}' not found in registry.")
                continue

            available = list(claw.registry.keys())
            matched_skill = None

            # Instant match for existing registered skills
            lowered = user_input.lower()
            if ("ram" in lowered or "memory" in lowered) and any("memory" in s or "ram" in s for s in available):
                matched_skill = next(s for s in available if "memory" in s or "ram" in s)
            elif "uptime" in lowered and "create" not in lowered and any("uptime" in s for s in available):
                matched_skill = next(s for s in available if "uptime" in s)
            elif ("ip" in lowered or "network" in lowered or "interface" in lowered) and "create" not in lowered and any("network" in s or "ip" in s for s in available):
                matched_skill = next(s for s in available if "network" in s or "ip" in s)

            if matched_skill:
                res = claw.execute_skill(matched_skill)
                print(f"[{matched_skill} Result]:")
                for k, v in res.items():
                    print(f"  {k}: {v}")
                continue

            # Route generic or synthesis queries
            decision = router.route(user_input, available_skills=available)
            intent = decision.get("intent", "shell_exec")
            target = decision.get("target", user_input)

            if intent == "skill_exec" and target in claw.registry:
                res = claw.execute_skill(target)
                print(f"[{target} Result]:")
                for k, v in res.items():
                    print(f"  {k}: {v}")

            elif intent == "skill_evolve" or lowered.startswith("create a tool"):
                tool_name = target if target and target != user_input else "custom_tool"
                print(f"[Supervisor] Evolving new skill '{tool_name}' via SkillClaw...")
                evolver.generate_tool(tool_name, decision.get("objective", user_input))

            else:
                print(f"[Jarvis -> Ultron Executing]: {user_input}")
                res = await supervisor.dispatch(user_input)
                stdout = res.get("stdout", "")
                stderr = res.get("stderr", "")
                if stdout:
                    print(f"[Ultron Output]:\n{stdout}")
                if stderr:
                    print(f"[Ultron Error]:\n{stderr}")

        except (KeyboardInterrupt, EOFError):
            print("\n[Vagar] Shutting down.")
            break

if __name__ == "__main__":
    asyncio.run(main())
