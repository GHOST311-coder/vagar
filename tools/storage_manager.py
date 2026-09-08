import os
import shutil

def storage_manager(args: str = ""):
    """Scans for large files or deletes a specified path if provided in the argument string."""
    try:
        # Clean up any quotes or extra whitespace from the raw argument string
        target_path = args.strip().strip("'").strip('"')
        
        if target_path:
            expanded = os.path.expanduser(target_path)
            if os.path.exists(expanded):
                size_mb = round(os.path.getsize(expanded) / (1024 * 1024), 2)
                os.remove(expanded)
                return {"status": "success", "message": f"Successfully deleted {expanded} (Freed {size_mb} MB)."}
            else:
                return {"status": "error", "message": f"Path not found: {expanded}"}
            
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
        return {
            "status": "success", 
            "large_files": large_files, 
            "message": "Scan complete. To delete a file, type: !skill storage_manager /sdcard/path/to/file"
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}
