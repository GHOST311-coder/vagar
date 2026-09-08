import sqlite3
import os

class ExecutionLedger:
    def __init__(self, db_path="ledger.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS execution_ledger (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT,
                    source TEXT,
                    command TEXT,
                    exit_code INTEGER,
                    stdout TEXT,
                    stderr TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()

    def log(self, task_id, source, command, exit_code, stdout, stderr):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO execution_ledger (task_id, source, command, exit_code, stdout, stderr)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (task_id, source, command, exit_code, stdout, stderr))
            conn.commit()
        # Auto-prune after insert to maintain lean size
        self.prune(keep_limit=200)

    def prune(self, keep_limit=200):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                DELETE FROM execution_ledger 
                WHERE id NOT IN (
                    SELECT id FROM execution_ledger 
                    ORDER BY id DESC LIMIT ?
                )
            """, (keep_limit,))
            conn.commit()

    def get_recent_context(self, limit=3):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT source, command, stdout, stderr, timestamp 
                FROM execution_ledger 
                ORDER BY id DESC LIMIT ?
            """, (limit,))
            rows = cursor.fetchall()
            if not rows:
                return "No previous execution history."
            
            context = []
            for r in reversed(rows):
                out = (r[2][:150] + "... [truncated]") if r[2] and len(r[2]) > 150 else (r[2] or r[3] or "none")
                context.append(f"[{r[0]}] ran '{r[1]}' -> Result: {out.strip()}")
            return "\n".join(context)
