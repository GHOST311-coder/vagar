import asyncio
from typing import Annotated
from livekit.agents import AutoSubscribe, JobContext, WorkerOptions, cli, llm
from livekit.agents.voice_assistant import VoiceAssistant
from livekit.plugins import deepgram, openai, silero

from core.supervisor import VagarSupervisor
from core.skillclaw import SkillClaw
from core.evolver import SkillEvolver
from agents.ultron import UltronWorker

class JarvisAgent:
    def __init__(self, supervisor: VagarSupervisor, claw: SkillClaw, evolver: SkillEvolver):
        self.supervisor = supervisor
        self.claw = claw
        self.evolver = evolver

    @llm.ai_callable(description="Execute a low-level terminal command or system audit via Ultron.")
    async def run_shell_command(
        self,
        command: Annotated[str, llm.TypeInfo(description="The exact bash command to run")]
    ) -> str:
        """Asynchronously dispatches long-running CLI tasks to Ultron."""
        res = await self.supervisor.dispatch(command=command, agent="ultron")
        if res.get("exit_code") == 0:
            return f"Command executed successfully: {res.get('stdout')}"
        return f"Command failed with error: {res.get('stderr')}"

    @llm.ai_callable(description="Run an existing skill or synthesize a brand new tool using SkillClaw.")
    async def invoke_skill(
        self,
        skill_name: Annotated[str, llm.TypeInfo(description="Name of the skill, e.g. battery_status or network_info")],
        objective: Annotated[str, llm.TypeInfo(description="What the skill should do if it needs to be generated")]
    ) -> str:
        """Executes or automatically evolves dynamic tools via SkillClaw and Ollama."""
        if skill_name not in self.claw.registry:
            created = self.evolver.generate_tool(skill_name, objective)
            if not created:
                return f"Unable to generate skill {skill_name}."
        try:
            output = await self.claw.execute_skill(skill_name)
            return f"Skill result: {output}"
        except Exception as e:
            return f"Error executing {skill_name}: {str(e)}"

async def entrypoint(ctx: JobContext):
    # Initialize core Vagar subsystems
    supervisor = VagarSupervisor()
    ultron = UltronWorker(supervisor)
    claw = SkillClaw()
    evolver = SkillEvolver(claw, ollama_url="http://127.0.0.1:11434", model="qwen2.5-coder:1.5b")

    # Pre-load existing Python skills
    for file in claw.tools_path.glob("*.py"):
        if file.name != "__init__.py":
            claw.register_tool_from_code(file.stem, file.read_text())

    # Start Ultron background worker queue
    asyncio.create_task(ultron.run_worker_loop())

    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)

    jarvis = JarvisAgent(supervisor, claw, evolver)

    assistant = VoiceAssistant(
        vad=silero.VAD.load(),
        stt=deepgram.STT(),
        llm=openai.LLM(model="gpt-4o-mini"),  # Or your local Ollama chat endpoint
        tts=deepgram.TTS(),
        fnc_ctx=jarvis
    )

    assistant.start(ctx.room)
    await assistant.say("Vagar system online. Supervisor and Ultron workers ready.", allow_interruptions=True)

if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))
