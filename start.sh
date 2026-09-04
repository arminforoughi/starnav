#!/bin/sh
# Start Star Nav in the background (reachable from phones on the same Wi-Fi). Re-run to restart.
cd "$(dirname "$0")"
pkill -f "python3 server.py 8000" 2>/dev/null
nohup python3 server.py 8000 --lan > starnav.log 2>&1 &
sleep 2 && tail -3 starnav.log
