
import platform
import os

def run(**kwargs):
    return {
        "system": platform.system(),
        "release": platform.release(),
        "arch": platform.machine(),
        "pid": os.getpid()
    }
