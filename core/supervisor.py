import asyncio
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict
import uuid

@dataclass
class AgentTask:
    action: str
    command: str
    task_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    agent: str = "ultron"
    future: asyncio.Future = field(default_factory=asyncio.Future)

class ExecutionLedger:
    def __init__(self, db_path: str = "data/vagar_state.db"):
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self._init_db()

    def _init_db(self):
        with self.conn:
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS execution_logs (
                    task_id TEXT PRIMARY KEY,
                    agent TEXT,
                    command TEXT,
                    exit_code INTEGER,
                    stdout TEXT,
                    stderr TEXT,
                    timestamp TEXT
                )
            """)

    def log(self, task_id: str, agent: str, command: str, exit_code: int, stdout: str, stderr: str):
        with self.conn:
            self.conn.execute(
                "INSERT INTO execution_logs VALUES (?, ?, ?, ?, ?, ?, ?)",
                (task_id, agent, command, exit_code, stdout, stderr, datetime.utcnow().isoformat())
            )

class VagarSupervisor:
    def __init__(self):
        self.queue: asyncio.Queue[AgentTask] = asyncio.Queue()
        self.ledger = ExecutionLedger()

    async def dispatch(self, command: str, action: str = "exec", agent: str = "ultron") -> Dict[str, Any]:
        task = AgentTask(action=action, command=command, agent=agent)
        await self.queue.put(task)
        return await task.future
