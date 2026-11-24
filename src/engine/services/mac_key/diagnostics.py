# -*- coding: utf-8 -*-
"""Read-only macOS environment diagnostics for the key-helper project.

Nothing here changes system state: all shell commands are read-only queries
(``csrutil status``, ``pgrep``, ``defaults read``). No key, plaintext, or
message content is ever returned.
"""
from __future__ import annotations

import os
import platform
import subprocess
import sys
from typing import Any

from . import tracememo
from .providers import provider_statuses
from .contract import MMKV_FORMAT_UNSUPPORTED

_READONLY_TIMEOUT = 3


def _run(argv: list[str]) -> str:
    try:
        proc = subprocess.run(argv, capture_output=True, text=True,
                              timeout=_READONLY_TIMEOUT, shell=False, check=False)
        return (proc.stdout or "").strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def wechat_version() -> str:
    for app in ("/Applications/WeChat.app", os.path.expanduser("~/Applications/WeChat.app")):
        plist = os.path.join(app, "Contents", "Info")
        if os.path.isfile(plist) or os.path.isdir(app):
            out = _run(["/usr/bin/defaults", "read", plist,
                        "CFBundleShortVersionString"])
            if out:
                return out
    return ""


def sip_enabled() -> bool | None:
    out = _run(["/usr/bin/csrutil", "status"])
    if not out:
        return None
    return "disabled" not in out.lower()


def wechat_running() -> bool:
    out = _run(["/usr/bin/pgrep", "-x", "WeChat"])
    return bool(out)


def _mmkv_layout(db_dir: str) -> dict[str, Any]:
    """Classify MMKV file layout without decrypting or printing content.

    Windows/legacy layout: first 4 bytes are the payload length followed by
    a 16-byte IV, ciphertext and a 16-byte GCM tag.
    Observed on macOS WeChat 4.2.0: fixed 16 KiB mmap files whose first 4
    bytes are usually zero — the Windows parser cannot handle them.
    """
    mmkv = os.path.join(db_dir or "", "MMKV")
    if not os.path.isdir(mmkv):
        return {"present": False, "files": 0, "layout": "none"}
    files = [n for n in os.listdir(mmkv) if n.endswith(".mmkv")]
    zero_head = 0
    sized = 0
    for name in files[:32]:
        path = os.path.join(mmkv, name)
        try:
            with open(path, "rb") as fh:
                head = fh.read(4)
        except OSError:
            continue
        if len(head) < 4:
            continue
        value = int.from_bytes(head, "little")
        if value == 0:
            zero_head += 1
        elif 33 <= value <= 16 * 1024 * 1024:
            sized += 1
    if not files:
        return {"present": True, "files": 0, "layout": "empty"}
    layout = "windows-gcm" if sized and not zero_head else "macos-mmap" if zero_head else "unknown"
    return {"present": True, "files": len(files), "layout": layout,
            "zero_head_files": zero_head, "sized_head_files": sized}


def collect(db_dir: str = "", db_count: int | None = None,
            salt_count: int | None = None) -> dict[str, Any]:
    """Snapshot used by the CLI, /api/health and the setup wizard."""
    is_mac = sys.platform == "darwin"
    arch = tracememo.get_mac_arch_snapshot() if is_mac else {}
    sip = tracememo.is_sip_enabled() if is_mac else None
    version = tracememo.detect_wechat_version() if is_mac else ""
    running = wechat_running() if is_mac else None
    providers = provider_statuses(db_dir) if is_mac else []
    ready = any(p.get("available") for p in providers)
    info: dict[str, Any] = {
        "system": "macos" if is_mac else platform.system().lower(),
        "arch": platform.machine(),
        "runtime_arch": arch.get("runtime_arch", ""),
        "hardware_arch": arch.get("hardware_arch", ""),
        "mac_key_flow": arch.get("mac_key_flow", "unsupported"),
        "python": platform.python_version(),
        "wechat_version": version,
        "helper_mode": tracememo.resolve_xkey_helper_mode(version) if is_mac else "",
        "sip_enabled": sip,
        "wechat_running": running,
        "db_dir": db_dir,
        "db_count": db_count,
        "salt_count": salt_count,
        "mmkv": _mmkv_layout(db_dir) if db_dir else {"present": False, "files": 0, "layout": "none"},
        "helper_inventory": tracememo.helper_inventory() if is_mac else {},
        "providers": providers,
        "auto_extract_ready": ready,
        "capture_ready": bool(ready and is_mac and sip is False and running),
    }
    if info["mmkv"].get("layout") == "macos-mmap":
        info["mmkv"]["code"] = MMKV_FORMAT_UNSUPPORTED
        info["mmkv"]["note"] = (
            "macOS 版 MMKV 与 Windows 的 4B长度+IV+密文+Tag 布局不同；"
            "直接复用现有 AES-GCM 策略不成立（按决策不再重复验证，走 helper 路线）。"
        )
    return info


def recommendations(info: dict[str, Any]) -> list[str]:
    """User-visible next steps for the TraceMemo-style advanced mode."""
    out: list[str] = []
    if info.get("system") != "macos":
        return ["当前不是 macOS；此诊断仅用于 Mac 自动提钥。"]
    if info.get("mac_key_flow") == "arch-mismatch":
        out.append(tracememo.ARCH_MISMATCH_ERROR)
        return out

    out.append("默认路线（零风险）：已有密钥文本走「手动输入密钥」，或打开已解密备份。")
    if not info.get("auto_extract_ready"):
        out.append("高级模式未就绪：请把 TraceMemo 的 xkey_helper / xkey_helper_4_1_13 "
                   "放到 resources/mac/（见 scripts/prepare_mac_key_helper.sh）。")
    elif info.get("sip_enabled"):
        out.append("helper 已就位，但 SIP 仍开启：按 docs/mac-auto-key.md 临时关闭 SIP "
                   "并重启后，才能执行高级模式；拿到密钥后请重新开启 SIP。")
    else:
        out.append("高级模式已就绪：先让微信停在未登录界面 → 点「一键提取」并完成管理员授权 "
                   "→ 提示出现后回微信点「登录」。")

    version = info.get("wechat_version") or ""
    if version and not version.startswith("4.1.13"):
        out.append(f"本机微信 {version}：参考实现已适配 4.1.13 / 4.1.8，"
                   "其它版本可能 SCAN_FAILED，不要连续重试。")
    elif version:
        out.append(f"本机微信 {version}：使用 xkey_helper_4_1_13 profile。")
    out.append("完全磁盘访问权限只影响读取微信数据目录，与自动提钥无关。")
    out.append("候选密钥一律先过数据库首页 HMAC 校验，不会把错误密钥写进配置。")
    return out
