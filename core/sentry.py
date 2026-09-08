import asyncio
from typing import Callable

class VagarSentry:
    def __init__(
        self,
        check_fn: Callable,
        alert_fn: Callable,
        process_fn: Callable = None,
        threshold_pct: float = 85.0,
        interval: int = 60
    ):
        self.check_fn = check_fn
        self.alert_fn = alert_fn
        self.process_fn = process_fn
        self.threshold = threshold_pct
        self.interval = interval
        self.running = False

    async def run_loop(self):
        self.running = True
        while self.running:
            try:
                stats = self.check_fn()
                pct_str = stats.get("memory_usage_pct", "0%").replace("%", "")
                usage = float(pct_str)
                if usage >= self.threshold:
                    details = ""
                    if self.process_fn:
                        proc_data = self.process_fn(limit=3)
                        top_procs = proc_data.get("top_processes", [])
                        proc_lines = [f"{p['command']} (PID {p['pid']}): {p['mem_pct']}%" for p in top_procs]
                        details = "\nTop: " + ", ".join(proc_lines)

                    self.alert_fn(
                        title="VAGAR MEMORY PRESSURE",
                        message=f"RAM at {usage}%! (Threshold: {self.threshold}%){details}"
                    )
            except Exception:
                pass
            await asyncio.sleep(self.interval)

    def stop(self):
        self.running = False
