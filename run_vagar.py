import asyncio
import sys
import uuid
from core.supervisor import VagarSupervisor
from core.skillclaw import SkillClaw
from core.evolver import SkillEvolver
from core.router import IntentRouter
from core.sentry import VagarSentry
from tools.voice_engine import speak, listen
from agents.jarvis import JarvisCognition
from tools.telephony import telephony_call, sms_send

async def main():
    supervisor = VagarSupervisor()
    claw = SkillClaw()
    evolver = SkillEvolver(claw)
    router = IntentRouter()
    jarvis = JarvisCognition()

    # Register telephony directly into SkillClaw if not already present
    if "telephony_call" not in claw.registry:
        claw.registry["telephony_call"] = telephony_call
    if "sms_send" not in claw.registry:
        claw.registry["sms_send"] = sms_send

    print("==================================================")
    print("           VAGAR JARVIS SUPERVISOR                ")
    print(" Modes:                                           ")
    print("   'listen' or '!voice' -> Single voice command   ")
    print("   '!loop'              -> Hands-free voice loop  ")
    print(" Manual overrides: !cmd, !skill, !list, !history  ")
    print("==================================================")

    speak("Jarvis online and ready.")
    continuous_mode = False

    while True:
        try:
            if continuous_mode:
                print("\n[Jarvis Hands-Free]: Listening...")
                voice_data = await asyncio.to_thread(listen)
                user_input = voice_data.get("transcript", "").strip()
                if not user_input:
                    await asyncio.sleep(0.5)
                    continue
                print(f"[Heard]: \"{user_input}\"")
                if user_input.lower() in ["stop listening", "exit voice", "cancel"]:
                    continuous_mode = False
                    speak("Continuous listening disabled.")
                    continue
            else:
                user_input = await asyncio.to_thread(input, "\nvagar> ")
                user_input = user_input.strip()
                if not user_input:
                    continue

            if user_input.lower() in ["exit", "quit"]:
                speak("Jarvis powering down.")
                print("[Jarvis] Offline.")
                sys.exit(0)

            if user_input.lower() == "!loop":
                continuous_mode = True
                speak("Continuous listening engaged. Say stop listening to exit.")
                continue

            if user_input.lower() in ["!voice", "voice", "listen"]:
                print("[Voice Engine]: Listening via microphone...")
                voice_data = await asyncio.to_thread(listen)
                transcript = voice_data.get("transcript", "").strip()
                if not transcript:
                    print("[Voice Engine]: No speech detected.")
                    speak("I didn't catch that.")
                    continue
                print(f"[Heard]: \"{transcript}\"")
                user_input = transcript

            if user_input.startswith("!cmd "):
                shell_cmd = user_input.split(" ", 1)[1].strip()
                print(f"[Jarvis Executing]: {shell_cmd}")
                res = await supervisor.dispatch(shell_cmd)
                if res.get("stdout"):
                    print(f"[Output]:\n{res['stdout']}")
                if res.get("stderr"):
                    print(f"[Error]:\n{res['stderr']}")
                continue

            if user_input == "!list":
                print(f"[Active Skills]: {list(claw.registry.keys())}")
                continue

            if user_input == "!history":
                print("[Recent History]:")
                print(supervisor.ledger.get_recent_context(limit=5))
                continue

            if user_input.startswith("!skill "):
                skill_name = user_input.split(" ", 1)[1].strip()
                if skill_name in claw.registry:
                    res = claw.execute_skill(skill_name)
                    print(f"[Skill Result]:\n{res}")
                else:
                    print(f"[Error]: Skill '{skill_name}' not found.")
                continue

            available = list(claw.registry.keys())
            lowered = user_input.lower()

            if lowered.startswith("create a tool") or lowered.startswith("create tool"):
                obj = user_input.split("tool", 1)[1].replace("to", "").strip()
                tool_slug = "_".join(obj.split()[:4]).lower()
                speak(f"Synthesizing tool {tool_slug}")
                print(f"[Jarvis] Evolving new skill '{tool_slug}'...")
                evolver.generate_tool(tool_slug, user_input)
                continue

            # Fast path routing for core tools
            matched_skill = None
            if "ping" in lowered and "network_ping_latency" in available:
                matched_skill = "network_ping_latency"
            elif "memory" in lowered and "system_memory_usage" in available:
                matched_skill = "system_memory_usage"
            elif "clean" in lowered and "sweep_cache" in available:
                matched_skill = "sweep_cache"
            elif "storage" in lowered and "check_srage_usage" in available:
                matched_skill = "check_srage_usage"

            if matched_skill:
                res = claw.execute_skill(matched_skill)
                print(f"[{matched_skill} Result]: {res}")
                speak(f"Executed {matched_skill}.")
                continue

            # General Cognitive Processing via Jarvis Local Brain
            response = jarvis.query_local_brain(user_input)
            if response:
                print(f"[Jarvis]: {response}")
                speak(response)
            else:
                res = await supervisor.dispatch(user_input)
                print(f"[Output]:\n{res.get('stdout', '')}")

        except (KeyboardInterrupt, EOFError):
            print("\n[Jarvis] Shutting down.")
            break

if __name__ == "__main__":
    asyncio.run(main())
