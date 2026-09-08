import asyncio
import sqlite3
from datetime import datetime
from typing import Dict, Any, List

class AgentTask:
    def __init__(self, action: str, command: str, agent: str = "ultron"):
        self.action = action
        self.command = command
        self.agent = agent
        self.future = asyncio.get_event_loop().create_future()

class ExecutionLedger:
    def __init__(self, db_path: str = "ledger.db"):
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.create_tables()

    def create_tables(self):
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

    def get_recent_context(self, limit: int = 3) -> str:
        with self.conn:
            cur = self.conn.cursor()
            cur.execute("""
                SELECT agent, command, stdout, stderr 
                FROM execution_logs 
                ORDER BY timestamp DESC 
                LIMIT ?
            """, (limit,))
            rows = cur.fetchall()

        if not rows:
            return "No previous execution history."

        context_lines = []
        for agent, cmd, stdout, stderr in reversed(rows):
            output = stdout.strip() if stdout else stderr.strip()
            # Truncate large outputs so context stays compact
            if len(output) > 200:
                output = output[:200] + "... [truncated]"
            context_lines.append(f"[{agent}] ran '{cmd}' -> Result: {output}")

        return "\n".join(context_lines)

class VagarSupervisor:
    def __init__(self):
        self.queue: asyncio.Queue[AgentTask] = asyncio.Queue()
        self.ledger = ExecutionLedger()

    async def dispatch(self, command: str, action: str = "exec", agent: str = "ultron") -> Dict[str, Any]:
        task = AgentTask(action=action, command=command, agent=agent)
        await self.queue.put(task)
        return await task.future
