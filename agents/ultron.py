import asyncio
import shlex
from typing import Dict, Any
from core.supervisor import VagarSupervisor, AgentTask

class UltronWorker:
    def __init__(self, supervisor: VagarSupervisor, default_timeout: float = 30.0):
        self.supervisor = supervisor
        self.timeout = default_timeout

    async def run_worker_loop(self):
        while True:
            task: AgentTask = await self.supervisor.queue.get()
            try:
                result = await self._execute_command(task.command)
                self.supervisor.ledger.log(
                    task_id=task.task_id,
                    agent=task.agent,
                    command=task.command,
                    exit_code=result["exit_code"],
                    stdout=result["stdout"],
                    stderr=result["stderr"]
                )
                task.future.set_result(result)
            except Exception as e:
                task.future.set_result({"status": "error", "error": str(e), "exit_code": -1})
            finally:
                self.supervisor.queue.task_done()

    async def _execute_command(self, command: str) -> Dict[str, Any]:
        parts = shlex.split(command)
        if not parts:
            return {"exit_code": -1, "stdout": "", "stderr": "Empty command"}

        proc = await asyncio.create_subprocess_exec(
            parts[0],
            *parts[1:],
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=self.timeout)
            return {
                "exit_code": proc.returncode,
                "stdout": stdout.decode("utf-8", errors="replace").strip()[:1000],
                "stderr": stderr.decode("utf-8", errors="replace").strip()[:500]
            }
        except asyncio.TimeoutError:
            try:
                proc.kill()
                await proc.wait()
            except ProcessLookupError:
                pass
            return {"exit_code": -1, "stdout": "", "stderr": f"Command timed out after {self.timeout}s"}
