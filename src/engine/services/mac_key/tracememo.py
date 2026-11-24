# -*- coding: utf-8 -*-
"""macOS auto key-extraction flow, ported from TraceMemo's ``KeyServiceMac``.

Reference: github.com/Wxw-Gu/TraceMemo — src/main/key-service-mac.ts,
src/shared/macos-arch.ts, src/main/services/connection-diagnostics.ts.

Call chain (same order and same decisions as the reference):
    arch snapshot (before SIP, so a Rosetta/x64 mismatch is reported first)
      -> SIP check
      -> Intel flow: intel_mac_key_helper status/capture (Frida runtime)
      -> Apple Silicon flow: WeChat version -> PID -> helper profile
         -> osascript "do shell script ... with administrator privileges"
         -> JSON payload -> failure-code mapping

Differences from the reference, dictated by this project:
* No helper binary is bundled. The user places TraceMemo's helper files in
  ``resources/mac/`` (see scripts/prepare_mac_key_helper.sh); only the *call
  contract* is reproduced here.
* A helper result is never trusted: every 64-hex candidate must pass the
  SQLCipher page-1 HMAC check in ``adapter.py`` before it reaches the config.
* Keys are never printed in full (``contract.mask_key``).
* ``keyKind=account`` is accepted as a candidate (the 4.1.13 helper returns
  exactly that). If it fails HMAC the adapter reports a derivation hint
  instead of pretending success.

Prerequisites for the advanced mode (user-visible, not hidden):
    macOS with SIP disabled + administrator password + WeChat logged out and
    waiting on the login screen; helper must match the WeChat version.
"""
from __future__ import annotations

import json
import os
import platform
import re
import subprocess
import sys
from typing import Any, Callable

from .contract import (
    KEY_HEX_RE,
    KeyCandidate,
    ProviderResult,
)

# ---------------------------------------------------------------------------
#  Error codes (user-visible; keep in sync with docs/mac-auto-key.md)
# ---------------------------------------------------------------------------
SIP_ENABLED = "SIP_ENABLED"
ARCH_MISMATCH_X64_ON_ARM = "ARCH_MISMATCH_X64_ON_ARM"
UNSUPPORTED_PLATFORM = "UNSUPPORTED_PLATFORM"
WECHAT_NOT_RUNNING = "WECHAT_NOT_RUNNING"
HELPER_NOT_FOUND = "HELPER_NOT_FOUND"
CAPTURE_TIMEOUT = "CAPTURE_TIMEOUT"
SCAN_FAILED = "SCAN_FAILED"
PERMISSION_DENIED = "PERMISSION_DENIED"
AUTH_TIMEOUT = "AUTH_TIMEOUT"
AUTH_CANCELLED = "AUTH_CANCELLED"
ACCOUNT_REQUIRED = "ACCOUNT_REQUIRED"
KEY_TOOL_UNAVAILABLE = "KEY_TOOL_UNAVAILABLE"
KEY_TOOL_FAILED = "KEY_TOOL_FAILED"
KEY_TOOL_TIMEOUT = "KEY_TOOL_TIMEOUT"
HELPER_EXEC_FAILED = "HELPER_EXEC_FAILED"
HELPER_RESULT_INVALID = "HELPER_RESULT_INVALID"

ARCH_MISMATCH_ERROR = (
    "当前 Mac 使用 Apple 芯片，但本程序正在以 Intel (x86_64) 方式运行。"
    "请改用 Apple Silicon (arm64) 版本的 Python / 应用后重试。"
)
SIP_ENABLED_ERROR = (
    "macOS 系统完整性保护（SIP）已开启，无法自动获取数据库密钥。"
    "这是参考实现 TraceMemo 的硬性前提：需在恢复模式执行 csrutil disable 并重启；"
    "拿到密钥后请按 Apple 官方方式重新开启 SIP。"
    "不方便调整系统设置时，请改用「手动输入密钥」或已解密备份。"
)
WECHAT_NOT_RUNNING_ERROR = (
    "未找到微信主进程，请先启动微信并停留在登录界面（如果已登录，请退出账号，"
    "只关闭窗口不算）。"
)
CAPTURE_TIMEOUT_ERROR = (
    "已完成管理员授权，但监听期间微信没有触发账号密钥派生。请先让微信停在登录界面，"
    "点击「一键提取」并完成系统授权后，再回到微信点击「登录」；已有登录凭据时通常不需要扫码。"
)
SCAN_SINK_ERROR = (
    "内存扫描失败：未匹配到目标函数特征（Sink pattern not found），当前微信版本可能暂未适配。"
    "建议参考 TraceMemo 的兼容矩阵：使用微信 4.1.13.8（或降级 4.1.8.100）→ 冷启动 → 再提取。"
    "请不要连续重试，以免触发微信安全模式或系统内存保护。"
)

RESOURCE_ENV = "WECHAT_EXPORT_MAC_RESOURCES"
HELPER_LEGACY = "xkey_helper"
HELPER_413 = "xkey_helper_4_1_13"
INTEL_HELPER = "macos-key-tool/intel_mac_key_helper"
DEFAULT_TIMEOUT_MS = 60_000

PrintFn = Callable[[str], None]


# ---------------------------------------------------------------------------
#  Resource discovery
# ---------------------------------------------------------------------------
def resource_roots() -> list[str]:
    """Where helper binaries may live. Never downloads or auto-installs."""
    roots: list[str] = [os.environ.get(RESOURCE_ENV, "")]

    try:
        from engine.platform_info import data_root
        roots.append(os.path.join(data_root(), "resources", "mac"))
    except Exception:
        pass

    here = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.normpath(os.path.join(here, "..", "..", "..", ".."))
    roots.append(os.path.join(project_root, "resources", "mac"))
    roots.append(os.path.join(os.getcwd(), "resources", "mac"))
    support = os.path.expanduser(
        "~/Library/Application Support/WeChatExport/resources/mac")
    roots.append(support)

    exe_dir = os.path.dirname(os.path.abspath(sys.executable))
    roots.append(os.path.join(os.path.dirname(exe_dir), "Resources", "resources", "mac"))
    roots.append(os.path.join(os.path.dirname(exe_dir), "Resources"))

    seen, out = set(), []
    for root in roots:
        if root and os.path.isdir(root) and root not in seen:
            seen.add(root)
            out.append(root)
    return out


def find_helper(name: str) -> str:
    for root in resource_roots():
        candidate = os.path.join(root, name)
        if os.path.isfile(candidate):
            return candidate
    return ""


def helper_inventory() -> dict[str, Any]:
    return {
        "roots": resource_roots(),
        "legacy": bool(find_helper(HELPER_LEGACY)),
        "wechat_4_1_13": bool(find_helper(HELPER_413)),
        "intel": bool(find_helper(INTEL_HELPER)),
    }


# ---------------------------------------------------------------------------
#  Read-only system probes
# ---------------------------------------------------------------------------
def _run(argv: list[str], timeout: int = 3) -> str:
    try:
        proc = subprocess.run(argv, capture_output=True, text=True,
                              timeout=timeout, shell=False, check=False)
        return (proc.stdout or "").strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _hardware_arch() -> str:
    out = _run(["/usr/sbin/sysctl", "-n", "hw.optional.arm64"], timeout=1)
    if out == "1":
        return "arm64"
    if out == "0":
        return "x64"
    return "unknown"


def _under_translation() -> bool:
    # sysctl.proc_translated == 1 means this process runs under Rosetta.
    out = _run(["/usr/sbin/sysctl", "-n", "sysctl.proc_translated"], timeout=1)
    return out == "1"


def _runtime_arch() -> str:
    machine = (platform.machine() or "").lower()
    if machine in ("arm64", "aarch64"):
        return "arm64"
    if machine in ("x86_64", "amd64", "i386"):
        return "x64"
    return machine or "unknown"


def resolve_mac_key_flow(os_name: str, hardware_arch: str,
                         runtime_arch: str, under_translation: bool) -> str:
    """Same ordering constraints as the reference implementation."""
    if os_name != "darwin":
        return "unsupported"
    if runtime_arch == "arm64":
        return "apple-silicon"
    if runtime_arch != "x64":
        return "unsupported"
    if under_translation:
        return "arch-mismatch"
    if hardware_arch == "arm64":
        return "arch-mismatch"
    return "intel"


def get_mac_arch_snapshot() -> dict[str, Any]:
    os_name = sys.platform
    snap = {
        "platform": os_name,
        "hardware_arch": _hardware_arch() if os_name == "darwin" else "unknown",
        "runtime_arch": _runtime_arch(),
        "under_translation": _under_translation() if os_name == "darwin" else False,
    }
    snap["mac_key_flow"] = resolve_mac_key_flow(
        os_name, snap["hardware_arch"], snap["runtime_arch"],
        snap["under_translation"])
    return snap


def parse_sip_enabled(status_output: str) -> bool:
    match = re.search(r"status:\s*([a-z]+)", status_output or "", re.IGNORECASE)
    if match:
        return match.group(1).lower() == "enabled"
    return "enabled" in (status_output or "").lower()


def is_sip_enabled() -> bool:
    return parse_sip_enabled(_run(["/usr/bin/csrutil", "status"]))


def detect_wechat_version() -> str:
    for app in ("/Applications/WeChat.app",
                os.path.expanduser("~/Applications/WeChat.app")):
        info = os.path.join(app, "Contents", "Info")
        if os.path.isfile(info + ".plist") or os.path.isdir(app):
            out = _run(["/usr/bin/defaults", "read", info,
                        "CFBundleShortVersionString"])
            if out:
                return out
    return ""


def get_wechat_pid() -> int:
    for argv in (["/usr/bin/pgrep", "-x", "WeChat"],
                 ["/usr/bin/pgrep", "-f", "WeChat.app/Contents/MacOS/WeChat"]):
        out = _run(argv)
        pids = []
        for line in out.splitlines():
            try:
                value = int(line.strip())
            except ValueError:
                continue
            if value > 0:
                pids.append(value)
        if pids:
            return max(pids)
    raise RuntimeError(WECHAT_NOT_RUNNING)


# ---------------------------------------------------------------------------
#  Invocation / failure mapping (parity with key-service-mac.ts)
# ---------------------------------------------------------------------------
def resolve_xkey_helper_mode(wechat_version: str) -> str:
    return ("wechat-4.1.13" if re.match(r"^4\.1\.13(?:\.|$)",
                                        (wechat_version or "").strip())
            else "legacy")


def build_apple_silicon_invocation(wechat_version: str, pid: int,
                                   timeout_ms: int = DEFAULT_TIMEOUT_MS) -> dict[str, Any]:
    mode = resolve_xkey_helper_mode(wechat_version)
    is_413 = mode == "wechat-4.1.13"
    wait_ms = max(120_000 if is_413 else 30_000, timeout_ms)
    timeout_seconds = -(-wait_ms // 1000) + (10 if is_413 else 30)
    return {
        "mode": mode,
        "resource_name": HELPER_413 if is_413 else HELPER_LEGACY,
        "args": ([str(pid), str(wait_ms), "--profile", "wechat-4.1.13", "--account"]
                 if is_413 else [str(pid), str(wait_ms)]),
        "wait_ms": wait_ms,
        "timeout_seconds": int(timeout_seconds),
        "exec_timeout_ms": int(timeout_seconds * 1000 + 5_000) if is_413
                           else wait_ms + 20_000,
    }


def map_xkey_helper_failure(raw_error: str,
                            fallback_code: str = HELPER_RESULT_INVALID) -> ProviderResult:
    text = (raw_error or "").strip()
    lowered = text.lower()
    parsed = re.search(r'(?:^|[\s"])(?:\\?"?)ERROR:([^:\s"}]+):?([^"}\r\n]*)',
                       text, re.IGNORECASE)
    code = (parsed.group(1).upper() if parsed else "") or ""
    detail = (parsed.group(2).strip() if parsed else "")

    if (code == CAPTURE_TIMEOUT
            or "timeout waiting for breakpoint hit" in lowered
            or "timeout waiting for sink hit" in lowered
            or "no_breakpoint_hit" in lowered):
        return ProviderResult(False, CAPTURE_TIMEOUT, CAPTURE_TIMEOUT_ERROR)
    if code == SCAN_FAILED and "sink pattern not found" in detail.lower():
        return ProviderResult(False, SCAN_FAILED, SCAN_SINK_ERROR)
    if code == SCAN_FAILED:
        return ProviderResult(False, SCAN_FAILED,
                              "内存扫描失败：当前微信版本或运行状态暂未适配。")
    if "permission denied" in lowered or code == PERMISSION_DENIED:
        return ProviderResult(False, code or PERMISSION_DENIED,
                              "管理员授权不足，无法读取微信进程内存。")
    return ProviderResult(
        False, code or fallback_code,
        f"密钥工具执行未完成（{code}），请确认微信仍在运行后重试。" if code
        else "密钥工具未返回有效密钥，请确认微信仍在运行后重试。")


def parse_xkey_helper_output(output: str) -> ProviderResult:
    payloads: list[dict[str, Any]] = []
    for match in re.finditer(r"\{[^{}]*\}", output or ""):
        try:
            obj = json.loads(match.group(0))
            if isinstance(obj, dict):
                payloads.append(obj)
        except (ValueError, TypeError):
            continue

    success = next((p for p in payloads
                    if p.get("success") is True and isinstance(p.get("key"), str)), None)
    if success:
        raw_key = str(success["key"]).strip()
        if raw_key.lower().startswith("0x"):
            raw_key = raw_key[2:]
        if KEY_HEX_RE.match(raw_key):
            kind = str(success.get("keyKind") or success.get("kind") or "db")
            return ProviderResult(
                True, "OK", "",
                candidates=(KeyCandidate(
                    key_hex=raw_key.lower(),
                    profile=str(success.get("profile") or ""),
                    kind=kind,
                ),),
                diagnostics={"key_kind": kind},
            )

    raw_error = ""
    for payload in payloads:
        value = payload.get("result") or payload.get("error")
        if isinstance(value, str) and value.strip():
            raw_error = value.strip()
            break
    return map_xkey_helper_failure(raw_error)


# ---------------------------------------------------------------------------
#  Apple Silicon provider
# ---------------------------------------------------------------------------
class AppleSiliconXkeyProvider:
    """``xkey_helper`` via osascript administrator privileges."""

    name = "xkey-helper"
    first_party = True

    def __init__(self, runner=None, environ: dict[str, str] | None = None):
        self._runner = runner
        self._env = environ if environ is not None else os.environ

    def _arch(self) -> dict[str, Any]:
        return get_mac_arch_snapshot()

    def status(self, db_dir: str = "") -> dict[str, Any]:
        arch = self._arch()
        if arch["mac_key_flow"] != "apple-silicon":
            return {"name": self.name, "available": False,
                    "reason": f"流程={arch['mac_key_flow']}", "first_party": True}
        version = detect_wechat_version()
        mode = resolve_xkey_helper_mode(version)
        helper = find_helper(HELPER_413 if mode == "wechat-4.1.13" else HELPER_LEGACY)
        if not helper:
            return {"name": self.name, "available": False,
                    "reason": HELPER_NOT_FOUND, "first_party": True,
                    "wechat_version": version, "mode": mode}
        return {
            "name": self.name, "available": True, "reason": "",
            "first_party": True, "wechat_version": version, "mode": mode,
            "sip_enabled": is_sip_enabled(),
            "helper": os.path.basename(helper),
        }

    def _osascript(self, helper_path: str, args: list[str],
                   timeout_seconds: int, exec_timeout_ms: int,
                   print_fn: PrintFn) -> str:
        lines = [
            f"set helperPath to {json.dumps(helper_path)}",
            'set cmd to quoted form of helperPath & " ' + " ".join(args) + '"',
            f"set timeoutSec to {timeout_seconds}",
            "try",
            "with timeout of timeoutSec seconds",
            "set outText to do shell script cmd with administrator privileges",
            "end timeout",
            'return "OK::" & outText',
            "on error errMsg number errNum",
            'return "ERR::" & errNum & "::" & errMsg',
            "end try",
        ]
        argv = ["/usr/bin/osascript"]
        for line in lines:
            argv.extend(["-e", line])
        print_fn("[MacKey] 正在请求管理员授权；授权后请在微信登录界面点击「登录」")
        timeout = max(1, exec_timeout_ms / 1000 + 5)
        run = self._runner or subprocess.run
        proc = run(argv, capture_output=True, text=True, timeout=timeout,
                   shell=False, check=False)
        return (getattr(proc, "stdout", "") or "").strip()

    def extract(self, db_dir: str, print_fn: PrintFn = print) -> ProviderResult:
        arch = self._arch()
        flow = arch["mac_key_flow"]
        if flow == "arch-mismatch":
            return ProviderResult(False, ARCH_MISMATCH_X64_ON_ARM,
                                  ARCH_MISMATCH_ERROR, provider=self.name)
        if flow != "apple-silicon":
            return ProviderResult(False, UNSUPPORTED_PLATFORM,
                                  "自动提钥仅支持 macOS（Apple Silicon）。",
                                  provider=self.name)

        if is_sip_enabled():
            return ProviderResult(False, SIP_ENABLED, SIP_ENABLED_ERROR,
                                  provider=self.name)

        version = detect_wechat_version()
        print_fn(f"[MacKey] 微信版本 {version or '未检测到'}；正在查找微信进程...")
        try:
            pid = get_wechat_pid()
        except RuntimeError:
            return ProviderResult(False, WECHAT_NOT_RUNNING,
                                  WECHAT_NOT_RUNNING_ERROR, provider=self.name)

        invocation = build_apple_silicon_invocation(version, pid)
        helper = find_helper(invocation["resource_name"])
        if not helper:
            return ProviderResult(
                False, HELPER_NOT_FOUND,
                f"找不到 {invocation['resource_name']}。请把 TraceMemo 的 helper 放到 "
                "resources/mac/（参见 scripts/prepare_mac_key_helper.sh），"
                "或改用「手动输入密钥」。",
                provider=self.name)
        if not os.access(helper, os.X_OK):
            return ProviderResult(False, HELPER_EXEC_FAILED,
                                  "helper 不可执行，请先运行 prepare_mac_key_helper.sh。",
                                  provider=self.name)

        print_fn(f"[MacKey] 使用 {os.path.basename(helper)} "
                 f"(profile={invocation['mode']}, 等待 {invocation['wait_ms'] // 1000}s)")

        try:
            output = self._osascript(
                helper, invocation["args"], invocation["timeout_seconds"],
                invocation["exec_timeout_ms"], print_fn)
        except subprocess.TimeoutExpired:
            return ProviderResult(
                False, AUTH_TIMEOUT,
                "管理员授权等待超时，请点击「一键提取」后及时完成系统授权。",
                provider=self.name)
        except OSError as exc:
            return ProviderResult(False, HELPER_EXEC_FAILED,
                                  f"密钥工具执行失败：{exc}", provider=self.name)

        if output.startswith("ERR::-128"):
            return ProviderResult(False, AUTH_CANCELLED, "已取消管理员授权。",
                                  provider=self.name)
        if output.startswith("ERR::"):
            parts = output.split("::")
            err_no = parts[1] if len(parts) > 1 else "UNKNOWN"
            result = map_xkey_helper_failure("::".join(parts[2:]),
                                             f"OSASCRIPT_{err_no}")
            return ProviderResult(False, result.code, result.message,
                                  provider=self.name)

        result = parse_xkey_helper_output(
            output[4:] if output.startswith("OK::") else output)
        return ProviderResult(result.ok, result.code, result.message,
                              candidates=result.candidates,
                              diagnostics=result.diagnostics,
                              provider=self.name)


# ---------------------------------------------------------------------------
#  Intel provider (Frida runtime, JSONL contract)
# ---------------------------------------------------------------------------
class IntelMacKeyProvider:
    """``intel_mac_key_helper status|capture`` on genuine Intel Macs."""

    name = "intel-mac-key-tool"
    first_party = True

    def __init__(self, runner=None):
        self._runner = runner

    def status(self, db_dir: str = "") -> dict[str, Any]:
        arch = get_mac_arch_snapshot()
        if arch["mac_key_flow"] != "intel":
            return {"name": self.name, "available": False,
                    "reason": f"流程={arch['mac_key_flow']}", "first_party": True}
        helper = find_helper(INTEL_HELPER)
        return {"name": self.name,
                "available": bool(helper), "first_party": True,
                "reason": "" if helper else KEY_TOOL_UNAVAILABLE,
                "sip_enabled": is_sip_enabled()}

    def _run_tool(self, args: list[str], timeout_ms: int,
                  print_fn: PrintFn) -> dict[str, Any]:
        helper = find_helper(INTEL_HELPER)
        if not helper:
            return {"success": False, "code": KEY_TOOL_UNAVAILABLE,
                    "error": "缺少 Intel Mac 工具"}
        run = self._runner or subprocess.run
        try:
            proc = run([helper] + args, capture_output=True, text=True,
                       timeout=timeout_ms / 1000 + 15, shell=False, check=False)
        except subprocess.TimeoutExpired:
            return {"success": False, "code": KEY_TOOL_TIMEOUT,
                    "error": "Intel Mac 密钥获取超时，请让微信回到未登录界面后重试"}
        except OSError as exc:
            return {"success": False, "code": KEY_TOOL_FAILED,
                    "error": f"无法启动 Intel Mac 密钥工具：{exc}"}

        final: dict[str, Any] = {}
        for line in (getattr(proc, "stdout", "") or "").splitlines():
            try:
                payload = json.loads(line)
            except (ValueError, TypeError):
                continue
            if not isinstance(payload, dict):
                continue
            if payload.get("type") == "progress" and payload.get("message"):
                print_fn(f"[MacKey] {payload['message']}")
            if payload.get("type") in ("result", "status"):
                final = payload
        if not final:
            return {"success": False, "code": KEY_TOOL_FAILED,
                    "error": "Intel Mac 密钥工具未返回结果"}
        return final

    def extract(self, db_dir: str, print_fn: PrintFn = print) -> ProviderResult:
        arch = get_mac_arch_snapshot()
        if arch["mac_key_flow"] != "intel":
            return ProviderResult(False, UNSUPPORTED_PLATFORM,
                                  "仅 Intel Mac 走此流程。", provider=self.name)
        if is_sip_enabled():
            return ProviderResult(False, SIP_ENABLED, SIP_ENABLED_ERROR,
                                  provider=self.name)
        account_root = os.path.dirname(os.path.abspath(db_dir)) if db_dir else ""
        if not account_root:
            return ProviderResult(False, ACCOUNT_REQUIRED, "请先选择微信账号目录。",
                                  provider=self.name)
        wait_ms = max(30_000, DEFAULT_TIMEOUT_MS)
        payload = self._run_tool(
            ["capture", "--account-root", account_root,
             "--timeout-ms", str(wait_ms)], wait_ms, print_fn)
        key = str(payload.get("key") or "").strip().lower()
        if payload.get("success") is True and KEY_HEX_RE.match(key):
            return ProviderResult(True, "OK", "",
                                  candidates=(KeyCandidate(key_hex=key),),
                                  provider=self.name)
        return ProviderResult(
            False, str(payload.get("code") or KEY_TOOL_FAILED),
            str(payload.get("error") or "未捕获到微信数据库密钥"),
            provider=self.name)
