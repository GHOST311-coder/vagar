class Vagar:
    def __init__(self):
        self.name = "Vagar"
        self.capabilities = [
            "System Diagnostics and Process Monitoring",
            "Network Reconnaissance and Socket Connectivity Auditing",
            "Security Assessment, Port Scanning, and Banner Grabbing",
            "Android Telemetry (SMS logs, Call logs, Contacts, and Clipboard Management)",
            "Dynamic Skill Evolution and Modular Tool Execution via Git"
        ]

    def introduce(self):
        intro_text = (
            f"Hello! I am {self.name}, your advanced autonomous local assistant "
            f"running natively on Termux. I am built to provide deep situational awareness "
            f"and command execution across your device and networks.\n\n"
            f"Here is a summary of what I am capable of doing:\n"
        )
        for cap in self.capabilities:
            intro_text += f" - {cap}\n"
        return intro_text

if __name__ == "__main__":
    v = Vagar()
    print(v.introduce())
