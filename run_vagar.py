import asyncio
import sys
import uuid
from core.supervisor import VagarSupervisor
from agents.ultron import UltronWorker
from core.skillclaw import SkillClaw
from core.evolver import SkillEvolver
from core.router import IntentRouter
from core.sentry import VagarSentry

async def main():
    supervisor = VagarSupervisor()
    worker = UltronWorker(supervisor)
    claw = SkillClaw()
    evolver = SkillEvolver(claw)
    router = IntentRouter()

    # Launch Ultron worker loop
    asyncio.create_task(worker.run_worker_loop())

    # Launch background Sentry watchdog
    if "system_memory_usage" in claw.registry and "send_notification" in claw.registry:
        sentry = VagarSentry(
            check_fn=claw.registry["system_memory_usage"],
            alert_fn=claw.registry["send_notification"],
            process_fn=claw.registry.get("top_memory_processes"),
            cleanup_fn=claw.registry.get("sweep_cache"),
            report_fn=claw.registry.get("generate_diagnostic_report"),
            threshold_pct=85.0,
            interval=60,
            report_interval=3600
        )
        asyncio.create_task(sentry.run_loop())

    print("==================================================")
    print("             VAGAR INTENT SUPERVISOR              ")
    print(" Speak/Type naturally in plain English:          ")
    print("   - 'How much RAM is free?'                      ")
    print("   - 'Full health check'                          ")
    print("   - 'Read diagnostic logs'                       ")
    print(" Manual overrides: !cmd, !skill, !list, !history  ")
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

            # Direct shell override
            if user_input.startswith("!cmd "):
                shell_cmd = user_input.split(" ", 1)[1].strip()
                print(f"[Ultron Executing]: {shell_cmd}")
                res = await supervisor.dispatch(shell_cmd)
                stdout = res.get("stdout", "")
                stderr = res.get("stderr", "")
                if stdout:
                    print(f"[Output]:\n{stdout}")
                if stderr:
                    print(f"[Error]:\n{stderr}")
                continue

            if user_input == "!list":
                print(f"[Skills Available]: {list(claw.registry.keys())}")
                continue

            if user_input == "!history":
                print("[Recent Task History]:")
                print(supervisor.ledger.get_recent_context(limit=5))
                continue

            if user_input.startswith("!skill "):
                skill_name = user_input.split(" ", 1)[1].strip()
                if skill_name in claw.registry:
                    res = claw.execute_skill(skill_name)
                    print(f"[Skill Result]:\n{res}")
                    supervisor.ledger.log(str(uuid.uuid4())[:8], "skillclaw", skill_name, 0, str(res), "")
                else:
                    print(f"[Error]: Skill '{skill_name}' not found.")
                continue

            available = list(claw.registry.keys())
            matched_skill = None
            lowered = user_input.lower()

            # Forced tool synthesis route
            if lowered.startswith("create a tool") or lowered.startswith("create tool"):
                obj = user_input.split("tool", 1)[1].replace("to", "").strip()
                tool_slug = "_".join(obj.split()[:4]).lower()
                print(f"[Supervisor] Evolving new skill '{tool_slug}' via SkillClaw...")
                evolver.generate_tool(tool_slug, user_input)
                continue

            # Fast-path skill routing
            if any(w in lowered for w in ["read log", "read logs", "show logs", "view logs", "summarize the last", "recent diagnostic"]) and "read_recent_diagnostic_logs" in available:
                matched_skill = "read_recent_diagnostic_logs"
            elif any(w in lowered for w in ["log report", "generate report", "save report", "take snapshot"]) and not any(w in lowered for w in ["compare", "difference", "between", "read"]) and "generate_diagnostic_report" in available:
                matched_skill = "generate_diagnostic_report"
            elif any(w in lowered for w in ["top process", "top processes", "heavy process", "memory consumer"]) and "top_memory_processes" in available:
                matched_skill = "top_memory_processes"
            elif any(w in lowered for w in ["clean", "sweep", "cache", "temp"]) and "sweep_cache" in available:
                matched_skill = "sweep_cache"
            elif any(w in lowered for w in ["cpu", "load", "processor"]) and any("cpu" in s for s in available):
                matched_skill = next(s for s in available if "cpu" in s)
            elif any(w in lowered for w in ["health", "full check"]) and any("health" in s for s in available):
                matched_skill = next(s for s in available if "health" in s)
            elif any(w in lowered for w in ["subnet", "hosts", "devices"]) and any("subnet" in s for s in available):
                matched_skill = next(s for s in available if "subnet" in s)
            elif any(w in lowered for w in ["port", "ports"]) and any("port" in s for s in available):
                matched_skill = next(s for s in available if "port" in s)
            elif any(w in lowered for w in ["notify", "notification", "alert"]) and any("notification" in s for s in available):
                matched_skill = next(s for s in available if "notification" in s)
            elif ("ram" in lowered or "memory" in lowered) and not any(w in lowered for w in ["why", "is", "should", "explain", "safe"]) and any("memory" in s for s in available):
                matched_skill = next(s for s in available if "memory" in s)
            elif "uptime" in lowered and any("uptime" in s for s in available):
                matched_skill = next(s for s in available if "uptime" in s)

            if matched_skill:
                res = claw.execute_skill(matched_skill)
                print(f"[{matched_skill} Result]:")
                if isinstance(res, dict):
                    for k, v in res.items():
                        print(f"  {k}: {v}")
                else:
                    print(f"  {res}")
                supervisor.ledger.log(str(uuid.uuid4())[:8], "skillclaw", matched_skill, 0, str(res), "")
                continue

            # Route natural language reasoning or shell fallback
            history = supervisor.ledger.get_recent_context(limit=3)
            decision = router.route(user_input, available_skills=available, history_context=history)
            intent = decision.get("intent", "shell_exec")
            target = decision.get("target", user_input)

            if intent == "answer":
                print(f"[Jarvis]: {decision.get('response', 'Understood.')}")

            elif intent == "skill_exec" and target in claw.registry:
                res = claw.execute_skill(target)
                print(f"[{target} Result]:")
                for k, v in res.items():
                    print(f"  {k}: {v}")
                supervisor.ledger.log(str(uuid.uuid4())[:8], "skillclaw", target, 0, str(res), "")

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
