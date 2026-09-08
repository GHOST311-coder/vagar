import asyncio
import json
import subprocess
from core.supervisor import VagarSupervisor
from agents.ultron import UltronWorker
from core.skillclaw import SkillClaw
from core.evolver import SkillEvolver

def speak(text: str):
    """Speaks aloud using Android's native TTS engine."""
    print(f"[Jarvis Voice]: {text}")
    subprocess.run(["termux-tts-speak", text], check=False)

def listen() -> str:
    """Captures speech from Android's microphone via Termux API."""
    print("\n[Jarvis] Listening... (speak now)")
    try:
        proc = subprocess.run(["termux-speech-to-text"], capture_output=True, text=True, timeout=10)
        output = proc.stdout.strip()
        if output:
            try:
                data = json.loads(output)
                return data.get("text", "")
            except json.JSONDecodeError:
                return output
    except Exception as e:
        print(f"[Voice Error]: {e}")
    return ""

async def handle_voice_prompt(text: str, supervisor: VagarSupervisor, claw: SkillClaw, evolver: SkillEvolver):
    text_lower = text.lower()
    
    # 1. Battery intent
    if "battery" in text_lower:
        speak("Checking battery levels.")
        result = await claw.execute_skill("battery_status")
        pct = result.get("percentage", "unknown")
        speak(f"The battery is currently at {pct} percent.")

    # 2. Network intent
    elif "network" in text_lower or "ip address" in text_lower:
        speak("Pulling network configuration.")
        result = await claw.execute_skill("network_info")
        ip = result.get("local_ip", "unknown")
        speak(f"Your local IP address is {ip}.")

    # 3. Direct bash execution
    elif text_lower.startswith("run command") or text_lower.startswith("execute"):
        cmd = text.split(" ", 2)[-1]
        speak(f"Running command {cmd} on Ultron.")
        res = await supervisor.dispatch(cmd, agent="ultron")
        out = res.get("stdout") or res.get("stderr")
        speak(f"Command finished. Output: {out[:120]}")

    # 4. Synthesize new skill on demand
    elif "create skill" in text_lower or "evolve" in text_lower:
        speak("Synthesizing new capability with SkillClaw.")
        tool_name = "custom_task"
        created = evolver.generate_tool(tool_name, text)
        if created:
            res = await claw.execute_skill(tool_name)
            speak("Skill deployed and executed successfully.")
        else:
            speak("Evolution failed AST validation.")

    else:
        speak(f"Heard: {text}. No matching automation routine.")

async def main():
    supervisor = VagarSupervisor()
    ultron = UltronWorker(supervisor)
    claw = SkillClaw()
    evolver = SkillEvolver(claw, ollama_url="http://127.0.0.1:11434", model="qwen2.5-coder:1.5b")

    # Load existing skills from disk
    for file in claw.tools_path.glob("*.py"):
        if file.name != "__init__.py":
            claw.register_tool_from_code(file.stem, file.read_text())

    # Start Ultron background worker
    worker_task = asyncio.create_task(ultron.run_worker_loop())

    speak("Vagar voice module active. Ready for input.")

    try:
        while True:
            # Run blocking mic input in a background thread so async queues remain active
            user_speech = await asyncio.to_thread(listen)
            if user_speech:
                print(f"[Recognized]: '{user_speech}'")
                if "exit" in user_speech.lower() or "shutdown" in user_speech.lower():
                    speak("Shutting down supervisor.")
                    break
                await handle_voice_prompt(user_speech, supervisor, claw, evolver)
            await asyncio.sleep(0.5)
    finally:
        worker_task.cancel()

if __name__ == "__main__":
    asyncio.run(main())
