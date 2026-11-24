#!/bin/bash
# Prepare the macOS advanced key helpers (TraceMemo-style) for WeChat Export.
#
# This project does NOT bundle, download or redistribute TraceMemo's helper
# binaries: that repository ships Mach-O files without source or a LICENSE /
# NOTICE file. You supply them yourself from a copy you already have.
#
# Usage (any of these source forms works):
#   ./scripts/prepare_mac_key_helper.sh "/Applications/TraceMemo.app/Contents/Resources/resources"
#   ./scripts/prepare_mac_key_helper.sh "/Volumes/TraceMemo/TraceMemo.app"
#   ./scripts/prepare_mac_key_helper.sh "/path/to/TraceMemo"          # git clone root
#   ./scripts/prepare_mac_key_helper.sh "/path/to/TraceMemo/resources"
#
# What it does (all inside this repository's resources/mac/, which is gitignored):
#   1. copies xkey_helper, xkey_helper_4_1_13, macos-key-tool/intel_mac_key_helper
#   2. verifies available .sha256 sidecars, then chmod 755
#   3. ad-hoc re-signs each Mach-O (codesign --force --sign -) and verifies it
#      per architecture, mirroring TraceMemo's scripts/after-pack.cjs
#
# Nothing here changes SIP, launches WeChat, or contacts the network.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TARGET="$PROJECT_ROOT/resources/mac"

usage() {
  echo "用法: $0 <TraceMemo 的 resources 目录 | .app | 仓库根目录>" >&2
  echo "例如: $0 \"/Applications/TraceMemo.app/Contents/Resources/resources\"" >&2
  echo "     $0 \"/path/to/TraceMemo/resources\"" >&2
  echo "     $0                    # 自动在常见安装位置查找" >&2
}

# Accept a resources dir, an .app bundle, or a git-clone root.
resolve_src() {
  local p="$1"
  [[ -d "$p" ]] || return 1
  local c
  for c in "$p" "$p/Contents/Resources/resources" "$p/Contents/Resources" \
           "$p/resources"; do
    if [[ -f "$c/xkey_helper" || -f "$c/xkey_helper_4_1_13" ]]; then
      echo "$c"
      return 0
    fi
  done
  return 1
}

if [[ $# -ge 1 ]]; then
  SRC="$(resolve_src "$1" || true)"
  if [[ -z "$SRC" ]]; then
    echo "错误: 不是有效的 TraceMemo resources 来源: $1" >&2
    echo "该目录下应能找到 xkey_helper 或 xkey_helper_4_1_13。" >&2
    usage
    exit 1
  fi
else
  SRC=""
  for candidate in \
    "/Applications/TraceMemo.app" \
    "$HOME/Applications/TraceMemo.app" \
    "$PWD/TraceMemo" \
    "$PWD/../TraceMemo"; do
    if found="$(resolve_src "$candidate" 2>/dev/null)"; then
      SRC="$found"
      break
    fi
  done
  if [[ -z "$SRC" ]]; then
    echo "错误: 未在常见位置找到 TraceMemo，请显式传入路径。" >&2
    usage
    exit 1
  fi
fi

echo "== 来源: $SRC"
echo "== 目标: $TARGET"
echo "提示: TraceMemo 仓库没有 LICENSE/NOTICE，helper 也无源码；"
echo "      这些二进制仅供本机使用，已由 .gitignore 排除，请勿随发行包再分发。"
mkdir -p "$TARGET/macos-key-tool"

copied=0
copy_one() {
  local rel="$1"
  local from="$SRC/$rel"
  local to="$TARGET/$rel"
  if [[ ! -f "$from" ]]; then
    echo "  - 跳过（未找到）: $rel"
    return 0
  fi
  if [[ -f "$from.sha256" ]]; then
    local expected actual
    expected="$(awk '{print $1}' "$from.sha256" | head -1 | tr '[:upper:]' '[:lower:]')"
    actual="$(shasum -a 256 "$from" | awk '{print $1}' | tr '[:upper:]' '[:lower:]')"
    if [[ -n "$expected" && "$expected" != "$actual" ]]; then
      echo "  ! SHA-256 不符，拒绝复制: $rel" >&2
      return 1
    fi
    echo "  ✓ SHA-256 校验通过: $rel"
  fi
  cp "$from" "$to"
  chmod 755 "$to"
  echo "  + 已复制: $rel  sha256=$(shasum -a 256 "$to" | awk '{print $1}' | cut -c1-16)…"
  copied=$((copied + 1))
}

copy_one "xkey_helper"
copy_one "xkey_helper_4_1_13"
copy_one "macos-key-tool/intel_mac_key_helper"

if [[ "$copied" -eq 0 ]]; then
  echo "错误: 没有复制到任何 helper，高级模式仍不可用。" >&2
  exit 1
fi

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "非 macOS，跳过 codesign。请在 Mac 上重新运行本脚本。"
  exit 0
fi

shopt -s nullglob
for helper in "$TARGET/xkey_helper" "$TARGET/xkey_helper_4_1_13" \
              "$TARGET/macos-key-tool/intel_mac_key_helper"; do
  [[ -f "$helper" ]] || continue
  if ! file "$helper" | grep -q "Mach-O"; then
    echo "  ! 不是 Mach-O，跳过签名: $helper" >&2
    continue
  fi
  /usr/bin/codesign --force --sign - "$helper"
  archs=$(/usr/bin/lipo -archs "$helper" 2>/dev/null || echo "")
  if [[ -n "$archs" ]]; then
    for arch in $archs; do
      /usr/bin/codesign --verify --strict --arch "$arch" "$helper"
      echo "  ✓ 签名校验通过 ($arch): $(basename "$helper")"
    done
  else
    /usr/bin/codesign --verify --strict "$helper"
    echo "  ✓ 签名校验通过: $(basename "$helper")"
  fi
done

echo ""
echo "完成。查看就绪状态："
echo "  cd \"$PROJECT_ROOT\" && PYTHONPATH=src .venv/bin/python -m engine.services.mac_key"
echo "高级模式的系统前置条件见 docs/mac-auto-key.md"
