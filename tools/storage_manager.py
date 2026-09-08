import os
import shutil

def storage_manager(file_to_delete: str = ""):
    """Scans for large files >50MB or deletes a specified file path."""
    try:
        if file_to_delete:
            target = os.path.expanduser(file_to_delete)
            if os.path.exists(target):
                size = os.path.getsize(target) / (1024 * 1024)
                os.remove(target)
                return {"status": "success", "message": f"Deleted {target}, freed {round(size, 2)} MB."}
            return {"status": "error", "message": f"File not found: {target}"}
            
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
        return {"status": "success", "large_files": large_files, "instruction": "To delete a file, invoke with the exact path."}
    except Exception as e:
        return {"status": "error", "message": str(e)}
