import subprocess
import shutil

def telephony_call(phone_number: str):
    if not shutil.which("termux-telephony-call"):
        return {"status": "error", "message": "termux-telephony-call not found"}
    try:
        subprocess.run(["termux-telephony-call", phone_number], check=True, timeout=10)
        return {"status": "success", "action": "call", "number": phone_number}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def sms_send(phone_number: str, message: str):
    if not shutil.which("termux-sms-send"):
        return {"status": "error", "message": "termux-sms-send not found"}
    try:
        subprocess.run(["termux-sms-send", "-n", phone_number, message], check=True, timeout=10)
        return {"status": "success", "action": "sms", "number": phone_number, "message": message}
    except Exception as e:
        return {"status": "error", "message": str(e)}
