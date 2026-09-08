#!/data/data/com.termux/files/usr/bin/bash
export PYTHONUNBUFFERED=1
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "[*] Starting Vagar Autonomous Supervisor..."
python run_vagar.py
