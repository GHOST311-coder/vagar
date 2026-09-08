import asyncio
import subprocess

class UltronWorker:
    """Ultron: Autonomous background worker and system execution engine."""
    def __init__(self, supervisor):
        self.supervisor = supervisor
        self.queue = asyncio.Queue()
        self.is_running = False

    async def enqueue(self, task_id: str, command: str):
        await self.queue.put((task_id, command))

    async def run_worker_loop(self):
        self.is_running = True
        while self.is_running:
            try:
                task = await asyncio.wait_for(self.queue.get(), timeout=1.0)
                task_id, command = task
                await self.execute_task(task_id, command)
                self.queue.task_done()
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

    async def execute_task(self, task_id: str, command: str):
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()
            out_str = stdout.decode().strip()
            err_str = stderr.decode().strip()
            self.supervisor.ledger.log(
                task_id, "ultron_worker", command, proc.returncode, out_str, err_str
            )
            return {"returncode": proc.returncode, "stdout": out_str, "stderr": err_str}
        except Exception as e:
            self.supervisor.ledger.log(task_id, "ultron_worker", command, 1, "", str(e))
            return {"returncode": 1, "stdout": "", "stderr": str(e)}
