import os
import shutil

def storage_manager(target_dir: str = "/sdcard", min_size_mb: int = 50):
    """Scans storage directories for large files and caches to help free up space."""
    large_files = []
    target_path = os.path.expanduser(target_dir)
    
    if not os.path.exists(target_path):
        return {"status": "error", "message": f"Directory {target_path} not found or inaccessible."}
        
    try:
        min_bytes = min_size_mb * 1024 * 1024
        for root, dirs, files in os.walk(target_path):
            if "Android/data" in root or "Android/obb" in root:
                continue
            for file in files:
                filepath = os.path.join(root, file)
                try:
                    size = os.path.getsize(filepath)
                    if size > min_bytes:
                        large_files.append({
                            "path": filepath,
                            "size_mb": round(size / (1024 * 1024), 2)
                        })
                except (PermissionError, FileNotFoundError):
                    continue
                    
        large_files = sorted(large_files, key=lambda x: x["size_mb"], reverse=True)[:20]
        total, used, free = shutil.disk_usage(target_path if target_path == "/" else "/sdcard")
        
        return {
            "status": "success",
            "storage_summary": {
                "total_gb": round(total / (2**30), 2),
                "used_gb": round(used / (2**30), 2),
                "free_gb": round(free / (2**30), 2)
            },
            "largest_files": large_files,
            "message": f"Found {len(large_files)} files larger than {min_size_mb}MB."
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}
