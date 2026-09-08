import os
import shutil

def storage_manager(path_arg: str = ""):
    """Scans for large files or deletes a specified path passed directly."""
    try:
        if path_arg:
            target = os.path.expanduser(path_arg)
            if os.path.exists(target):
                size = os.path.getsize(target) / (1024 * 1024)
                os.remove(target)
                return {"status": "success", "message": f"Successfully deleted {target} (Freed {round(size, 2)} MB)."}
            return {"status": "error", "message": f"Path not found: {target}"}
            
        large_files = []
        for root, dirs, files in os.walk("/sdcard"):
            if "Android/data" in root or "Android/obb" in root:
                continue
            for file in files:
                filepath = os.path.join(root, file)
                try:
                    size = os.path.getsize(filepath)
                    if size > 50 * 1024 * 1024:
                        large_files.append({"path": filepath, "size_mb": round(size / (1024 * 1024), 2)})
                except Exception:
                    continue
                    
        large_files = sorted(large_files, key=lambda x: x["size_mb"], reverse=True)[:15]
        return {"status": "success", "large_files": large_files, "instruction": "To delete, run: !skill storage_manager /sdcard/path/to/file"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
