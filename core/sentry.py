import asyncio
from typing import Callable

class VagarSentry:
    def __init__(self, check_fn: Callable, alert_fn: Callable, threshold_pct: float = 85.0, interval: int = 60):
        self.check_fn = check_fn
        self.alert_fn = alert_fn
        self.threshold = threshold_pct
        self.interval = interval
        self.running = False

    async def run_loop(self):
        self.running = True
        while self.running:
            try:
                stats = self.check_fn()
                pct_str = stats.get("memory_usage_pct", "0%").replace("%", "")
                if float(pct_str) >= self.threshold:
                    self.alert_fn(
                        title="VAGAR MEMORY WARNING",
                        message=f"RAM usage at {pct_str}%! Exceeds safe threshold ({self.threshold}%)."
                    )
            except Exception:
                pass
            await asyncio.sleep(self.interval)

    def stop(self):
        self.running = False
