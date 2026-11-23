#!/usr/bin/env bash
# Lightweight macOS build → dist/WeChat Export.app + DMG
# Requires: Python 3.11+, pip. Optional: create-dmg (else uses hdiutil).
set -euo pipefail
cd "$(dirname "$0")"
ROOT="$(pwd)"

ARCH="$(uname -m)"
case "$ARCH" in
  arm64|aarch64) ARCH_TAG="arm64" ;;
  x86_64) ARCH_TAG="x86_64" ;;
  *) ARCH_TAG="$ARCH" ;;
esac

PY="${PYTHON:-}"
if [[ -z "$PY" ]]; then
  if [[ -x "$ROOT/.venv/bin/python" ]]; then
    PY="$ROOT/.venv/bin/python"
  elif command -v python3 >/dev/null 2>&1; then
    PY="$(command -v python3)"
  else
    echo "[!] python3 not found" >&2
    exit 1
  fi
fi

echo "[*] Python: $PY ($("$PY" -c 'import sys; print(sys.version.split()[0])'))"
echo "[*] Installing build dependencies..."
if "$PY" -m pip --version >/dev/null 2>&1; then
  "$PY" -m pip install -q -r requirements-build.txt
elif command -v uv >/dev/null 2>&1; then
  uv pip install --python "$PY" -r requirements-build.txt
elif [[ -x "$HOME/.local/bin/uv" ]]; then
  "$HOME/.local/bin/uv" pip install --python "$PY" -r requirements-build.txt
else
  echo "[!] Neither pip nor uv available for $PY" >&2
  exit 1
fi

# Drop accidental local config from the src tree so it is not bundled.
rm -f "$ROOT/src/.wechat_exp_config.json"

echo "[*] Cleaning previous macOS outputs..."
rm -rf "$ROOT/build/wechat_exp_macos" \
       "$ROOT/dist/wechat_exp" \
       "$ROOT/dist/WeChat Export.app" \
       "$ROOT/dist/dmg_stage" \
       "$ROOT/dist"/WeChatExport-*-macos-*.dmg

VER="$("$PY" -c 'from pathlib import Path; import sys; sys.path.insert(0,"src"); from engine.version import VERSION; print(VERSION)')"
echo "[*] App version: $VER"

echo "[*] PyInstaller (macOS .app)..."
"$PY" -m PyInstaller --noconfirm --clean \
  --distpath "$ROOT/dist" \
  --workpath "$ROOT/build/wechat_exp_macos" \
  "$ROOT/wechat_exp_macos.spec"

APP="$ROOT/dist/WeChat Export.app"
if [[ ! -d "$APP" ]]; then
  echo "[!] Missing: $APP" >&2
  exit 1
fi

echo "[*] Ad-hoc codesign (deep)..."
codesign --force --deep -s - "$APP" 2>/dev/null || \
  echo "[!] codesign failed — Gatekeeper may block until right-click → Open"

DMG_NAME="WeChatExport-v${VER}-macos-${ARCH_TAG}.dmg"
DMG_PATH="$ROOT/dist/$DMG_NAME"
STAGE="$ROOT/dist/dmg_stage"
rm -rf "$STAGE"
mkdir -p "$STAGE"
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
# Short readme for first-run Gatekeeper tip
cat > "$STAGE/README-macOS.txt" <<'EOF'
WeChat Export for macOS (analysis / export)

1. Drag "WeChat Export.app" into Applications.
2. First launch: right-click the app → Open (Gatekeeper; build is not notarized).
3. Grant Full Disk Access if you need to read WeChat sandbox data.
4. Prefer: paste DB keys manually, or open an already-decrypted backup.
5. Auto process-memory key extract is Windows-only.
6. Data/config: ~/Library/Application Support/WeChatExport/
7. Optional: brew install ffmpeg
EOF

echo "[*] Creating DMG: $DMG_NAME"
rm -f "$DMG_PATH"
if command -v create-dmg >/dev/null 2>&1; then
  create-dmg \
    --volname "WeChat Export" \
    --window-pos 200 120 \
    --window-size 640 360 \
    --icon-size 100 \
    --icon "WeChat Export.app" 160 160 \
    --hide-extension "WeChat Export.app" \
    --app-drop-link 460 160 \
    "$DMG_PATH" \
    "$STAGE" || true
fi
if [[ ! -f "$DMG_PATH" ]]; then
  # Portable fallback — no Homebrew create-dmg required
  hdiutil create -volname "WeChat Export" -srcfolder "$STAGE" \
    -ov -format UDZO "$DMG_PATH"
fi

echo
echo "[+] Done:"
echo "    $APP"
echo "    $DMG_PATH"
echo "    First open: right-click → Open (unsigned / not notarized)"
