#!/data/data/com.termux/files/usr/bin/bash
SESSION="vagar_session"

tmux has-session -t $SESSION 2>/dev/null

if [ $? != 0 ]; then
    echo "[*] Launching Vagar inside background tmux session: $SESSION"
    tmux new-session -d -s $SESSION "bash ./start_vagar.sh"
    echo "[+] Session active. Use './attach_vagar.sh' to view/interact."
else
    echo "[!] Vagar is already running in tmux session: $SESSION"
fi
