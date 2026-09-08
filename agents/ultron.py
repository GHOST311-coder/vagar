import asyncio
import os
import uuid
from pathlib import Path
from core.supervisor import VagarSupervisor

class UltronWorker:
    def __init__(self, supervisor: VagarSupervisor, default_timeout: int = 15, sandbox_dir: str = "sandbox"):
        self.supervisor = supervisor
        self.timeout = default_timeout
        self.sandbox_path = Path(sandbox_dir).resolve()
        self.sandbox_path.mkdir(exist_ok=True)

    async def execute_task(self, task) -> None:
        stdout_str = ""
        stderr_str = ""
        exit_code = 1
        task_id = getattr(task, "id", str(uuid.uuid4())[:8])

        try:
            process = await asyncio.create_subprocess_shell(
                task.command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.sandbox_path),
                env=os.environ.copy()
            )

            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(),
                timeout=self.timeout
            )
            stdout_str = stdout_bytes.decode(errors="replace").strip()
            stderr_str = stderr_bytes.decode(errors="replace").strip()
            exit_code = process.returncode if process.returncode is not None else 0

        except asyncio.TimeoutError:
            try:
                process.kill()
                await process.wait()
            except Exception:
                pass
            stderr_str = f"[Ultron Error] Execution timed out after {self.timeout} seconds."
            exit_code = 124

        except Exception as e:
            stderr_str = f"[Ultron Internal Failure]: {type(e).__name__} - {str(e)}"
            exit_code = 1

        try:
            self.supervisor.ledger.log(
                task_id=task_id,
                agent=task.agent,
                command=task.command,
                exit_code=exit_code,
                stdout=stdout_str,
                stderr=stderr_str
            )
        except Exception:
            pass

        result_payload = {
            "task_id": task_id,
            "exit_code": exit_code,
            "stdout": stdout_str,
            "stderr": stderr_str
        }
        if not task.future.done():
            task.future.set_result(result_payload)

    async def run_worker_loop(self) -> None:
        while True:
            task = await self.supervisor.queue.get()
            if task.agent == "ultron":
                await self.execute_task(task)
            self.supervisor.queue.task_done()
