import os
import shutil

def run(**kwargs):
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    removed_dirs = 0
    removed_files = 0
    reclaimed_bytes = 0

    for root, dirs, files in os.walk(project_root, topdown=False):
        for name in files:
            if name.endswith(('.pyc', '.pyo', '.tmp')):
                filepath = os.path.join(root, name)
                try:
                    reclaimed_bytes += os.path.getsize(filepath)
                    os.remove(filepath)
                    removed_files += 1
                except Exception:
                    pass

        for name in dirs:
            if name == "__pycache__":
                dirpath = os.path.join(root, name)
                try:
                    shutil.rmtree(dirpath)
                    removed_dirs += 1
                except Exception:
                    pass

    return {
        "status": "success",
        "pycache_dirs_removed": removed_dirs,
        "temp_files_removed": removed_files,
        "space_reclaimed_kb": round(reclaimed_bytes / 1024, 2)
    }
