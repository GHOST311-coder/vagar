import shutil
import os

def run(**kwargs):
    """
    Return a pure dict with all results:
    {
        "total_gb": <int>,
        "free_gb": <int>
    }
    """
    usage = shutil.disk_usage('/')
    total_gb = int(usage.total / (1024**3))
    free_gb = int(usage.free / (1024**3))
    return {
        "total_gb": total_gb,
        "free_gb": free_gb
    }