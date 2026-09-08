import subprocess
import shutil
import json
import datetime

class HermesRelay:
    """Hermes: Inter-agent messaging, event dispatch, and Termux notification broadcaster."""
    def __init__(self, ledger=None):
        self.ledger = ledger

    def notify(self, title: str, content: str, priority: str = "high"):
        if shutil.which("termux-notification"):
            try:
                subprocess.run([
                    "termux-notification",
                    "--title", f"[Hermes] {title}",
                    "--content", str(content),
                    "--priority", priority,
                    "--id", "vagar_hermes"
                ], check=True, timeout=5)
                return {"status": "success", "channel": "termux-notification"}
            except Exception as e:
                return {"status": "error", "message": str(e)}
        return {"status": "fallback", "message": f"[{title}] {content}"}

    def broadcast(self, sender: str, event_type: str, payload: dict):
        timestamp = datetime.datetime.now().isoformat()
        event_record = {
            "timestamp": timestamp,
            "sender": sender,
            "event": event_type,
            "payload": payload
        }
        if self.ledger:
            self.ledger.log(
                f"hermes_{sender}_{event_type}",
                "hermes_relay",
                str(payload),
                0,
                json.dumps(event_record),
                ""
            )
        return event_record
