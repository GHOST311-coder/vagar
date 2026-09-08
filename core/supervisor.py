import asyncio
import os
import uuid
from core.ledger import ExecutionLedger

class VagarSupervisor:
    def __init__(self):
        self.ledger = ExecutionLedger()
        self.queue = asyncio.Queue()
        self.project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    async def dispatch(self, command: str, timeout: int = 15):
        task_id = str(uuid.uuid4())[:8]
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.project_root
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            out = stdout.decode().strip()
            err = stderr.decode().strip()
            exit_code = proc.returncode

            self.ledger.log(task_id, "ultron", command, exit_code, out, err)
            return {"task_id": task_id, "exit_code": exit_code, "stdout": out, "stderr": err}

        except asyncio.TimeoutError:
            proc.kill()
            self.ledger.log(task_id, "ultron", command, -1, "", "Execution timed out")
            return {"task_id": task_id, "exit_code": -1, "stdout": "", "stderr": "Execution timed out"}
        except Exception as e:
            self.ledger.log(task_id, "ultron", command, -1, "", str(e))
            return {"task_id": task_id, "exit_code": -1, "stdout": "", "stderr": str(e)}
