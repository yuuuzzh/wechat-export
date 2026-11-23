#!/bin/bash
# Double-click in Finder to start WeChat Export (macOS).
cd "$(dirname "$0")"
ROOT="$(pwd)"

open_url() {
  (sleep 1.2; open "http://127.0.0.1:5000" >/dev/null 2>&1) &
}

if [[ -d "$ROOT/dist/WeChat Export.app" ]]; then
  echo "[*] Starting dist/WeChat Export.app ..."
  open "$ROOT/dist/WeChat Export.app"
  exit 0
fi

if [[ -x "$ROOT/dist/wechat_exp/wechat_exp" ]]; then
  echo "[*] Starting dist/wechat_exp/wechat_exp ..."
  echo "[i] Keep this window open. Press Ctrl+C to stop."
  open_url
  exec "$ROOT/dist/wechat_exp/wechat_exp"
fi

PY=""
if [[ -x "$ROOT/.venv/bin/python" ]]; then
  PY="$ROOT/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PY="$(command -v python3)"
else
  echo "[!] python3 not found. Install Python 3 or run ./quick_build_macos.sh first."
  read -r -p "Press Enter to close..."
  exit 1
fi

echo "[*] Source mode: $PY src/main.py"
echo "[i] This Terminal window is the local service — keep it open."
echo "[i] Browser: http://127.0.0.1:5000"
open_url
exec "$PY" "$ROOT/src/main.py"
