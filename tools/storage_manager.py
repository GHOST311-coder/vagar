import os
import shutil

def storage_manager(action: str = "scan", file_path: str = "", min_size_mb: int = 50):
    """Scans storage for large files or deletes a specific file to free up space."""
    try:
        if action == "delete" and file_path:
            expanded_path = os.path.expanduser(file_path)
            if os.path.exists(expanded_path):
                size_mb = round(os.path.getsize(expanded_path) / (1024 * 1024), 2)
                os.remove(expanded_path)
                return {
                    "status": "success",
                    "message": f"Successfully deleted {expanded_path} (Freed {size_mb} MB)."
                }
            else:
                return {"status": "error", "message": f"File not found: {expanded_path}"}
        
        large_files = []
        target_path = os.path.expanduser("/sdcard")
        
        if not os.path.exists(target_path):
            return {"status": "error", "message": f"Directory {target_path} not found or inaccessible."}
            
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
        total, used, free = shutil.disk_usage("/sdcard")
        
        return {
            "status": "success",
            "storage_summary": {
                "total_gb": round(total / (2**30), 2),
                "used_gb": round(used / (2**30), 2),
                "free_gb": round(free / (2**30), 2)
            },
            "largest_files": large_files,
            "message": f"Found {len(large_files)} files > {min_size_mb}MB. To delete, use: !skill storage_manager action=delete file_path=/path/to/file"
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}
