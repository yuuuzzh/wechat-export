# -*- coding: utf-8 -*-
"""Pluggable macOS key providers.

Two hard product rules (see docs/platform.md) are enforced here:

1. **No binary is bundled, downloaded, or auto-discovered.** A helper path must
   be configured explicitly by the user via an environment variable.
2. **No privilege escalation, no injection, no SIP changes.** This module only
   runs a plain ``subprocess`` with ``shell=False`` and parses its stdout.
   Anything requiring elevated rights, debugger attach, or library injection
   lives in the helper the user chose, not here. We never do it on their behalf.

The abstraction exists so that a future first-party native helper can replace
``ExternalHelperProvider`` without touching the extraction strategy chain, the
config format, or the UI.
"""
from __future__ import annotations

import hashlib
import os
import shlex
import subprocess
from typing import Any, Callable

from .contract import (
    ACCOUNT_KEY_REQUIRED,
    HELPER_FAILED,
    HELPER_HASH_MISMATCH,
    HELPER_NOT_CONFIGURED,
    HELPER_NOT_EXECUTABLE,
    HELPER_OUTPUT_INVALID,
    HELPER_TIMEOUT,
    NO_VERIFIED_KEY,
    ProviderResult,
    parse_helper_output,
)

ENV_HELPER_PATH = "WECHAT_EXPORT_MAC_KEY_HELPER"
ENV_HELPER_SHA256 = "WECHAT_EXPORT_MAC_KEY_HELPER_SHA256"
ENV_HELPER_ARGS = "WECHAT_EXPORT_MAC_KEY_HELPER_ARGS"
ENV_HELPER_TIMEOUT = "WECHAT_EXPORT_MAC_KEY_HELPER_TIMEOUT"

DEFAULT_ARGS_TEMPLATE = "--db-dir {db_dir} --json"
DEFAULT_TIMEOUT_SEC = 90


class MacKeyProvider:
    """Interface every macOS key source implements."""

    name = "base"
    #: True when this provider is a first-party, no-extra-permission path.
    first_party = False

    def status(self, db_dir: str = "") -> dict[str, Any]:
        return {"name": self.name, "available": False, "reason": "not implemented"}

    def extract(self, db_dir: str, print_fn: Callable[[str], None] = print) -> ProviderResult:
        raise NotImplementedError


class ExternalHelperProvider(MacKeyProvider):
    """Run a user-supplied helper and ingest its JSON output.

    Contract v1: the helper is invoked as
    ``helper --db-dir <db_storage> --json`` (overridable with
    ``WECHAT_EXPORT_MAC_KEY_HELPER_ARGS``; ``{db_dir}`` is substituted) and
    prints JSON objects on stdout. TraceMemo-style single-key output is
    accepted as-is.
    """

    name = "external-helper"
    first_party = False

    def __init__(self, environ: dict[str, str] | None = None, runner=None):
        self._env = environ if environ is not None else os.environ
        self._runner = runner  # test seam: callable(cmd, **kwargs) -> CompletedProcess

    def _path(self) -> str:
        return str(self._env.get(ENV_HELPER_PATH, "")).strip()

    def _timeout(self) -> int:
        try:
            return max(1, min(600, int(self._env.get(ENV_HELPER_TIMEOUT, DEFAULT_TIMEOUT_SEC))))
        except (TypeError, ValueError):
            return DEFAULT_TIMEOUT_SEC

    def _verify_hash(self, path: str) -> str:
        expected = str(self._env.get(ENV_HELPER_SHA256, "")).strip().lower()
        if not expected:
            return ""
        digest = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                digest.update(chunk)
        return "" if digest.hexdigest() == expected else HELPER_HASH_MISMATCH

    def status(self, db_dir: str = "") -> dict[str, Any]:
        path = self._path()
        if not path:
            return {
                "name": self.name,
                "available": False,
                "reason": f"未配置 {ENV_HELPER_PATH}",
                "first_party": False,
            }
        if not os.path.isfile(path) or not os.access(path, os.X_OK):
            return {
                "name": self.name,
                "available": False,
                "reason": HELPER_NOT_EXECUTABLE,
                "first_party": False,
            }
        mismatch = self._verify_hash(path)
        if mismatch:
            return {
                "name": self.name,
                "available": False,
                "reason": mismatch,
                "first_party": False,
            }
        return {"name": self.name, "available": True, "reason": "", "first_party": False}

    def extract(self, db_dir: str, print_fn: Callable[[str], None] = print) -> ProviderResult:
        path = self._path()
        if not path:
            return ProviderResult(
                False, HELPER_NOT_CONFIGURED,
                "未配置外部 helper：本工具不捆绑、不下载、不自动发现提钥程序。"
                "如已有可信 helper，请显式设置 "
                f"{ENV_HELPER_PATH} 后再试；否则请用「手动输入密钥」或已解密备份。",
                provider=self.name,
            )
        if not os.path.isfile(path) or not os.access(path, os.X_OK):
            return ProviderResult(
                False, HELPER_NOT_EXECUTABLE,
                "helper 路径不存在或不可执行（不自动修复权限）。",
                provider=self.name,
            )
        mismatch = self._verify_hash(path)
        if mismatch:
            return ProviderResult(
                False, HELPER_HASH_MISMATCH,
                "helper 的 SHA-256 与配置不一致，已拒绝执行。",
                provider=self.name,
            )

        template = str(self._env.get(ENV_HELPER_ARGS, DEFAULT_ARGS_TEMPLATE))
        try:
            args = [part.replace("{db_dir}", db_dir)
                    for part in shlex.split(template)]
        except ValueError:
            return ProviderResult(
                False, HELPER_OUTPUT_INVALID,
                f"{ENV_HELPER_ARGS} 不是合法的参数模板。", provider=self.name)

        cmd = [path] + args
        print_fn(f"[MacKey] 调用外部 helper（{len(cmd)} 个参数，超时 {self._timeout()}s，不提权）")
        try:
            run = self._runner or subprocess.run
            proc = run(cmd, capture_output=True, text=True, timeout=self._timeout(),
                       shell=False, check=False)
        except subprocess.TimeoutExpired:
            return ProviderResult(False, HELPER_TIMEOUT,
                                 "helper 超时。请勿反复重试，先确认微信状态与 helper 版本。",
                                 provider=self.name)
        except OSError as exc:
            return ProviderResult(False, HELPER_FAILED, f"helper 启动失败：{exc}",
                                  provider=self.name)

        stdout = (getattr(proc, "stdout", "") or "")[:1_048_576]
        stderr = (getattr(proc, "stderr", "") or "")[:4096]
        candidates, account_seen, parse_error = parse_helper_output(stdout)

        if account_seen and not candidates:
            return ProviderResult(
                False, ACCOUNT_KEY_REQUIRED,
                "helper 只返回了账号主密钥标记（keyKind=account）却没有有效 64 位 hex 密钥；"
                "若后续 HMAC 全部不通过，可能需要补齐 PBKDF2 派生层。",
                provider=self.name,
            )
        if not candidates:
            detail = parse_error or stderr.strip()[:160] or "helper 未返回任何 64 位十六进制密钥"
            return ProviderResult(False, NO_VERIFIED_KEY, detail, provider=self.name)

        print_fn(f"[MacKey] helper 返回 {len(candidates)} 个候选，将逐一做 page1 HMAC 校验")
        return ProviderResult(True, "OK", "", candidates=tuple(candidates),
                              provider=self.name,
                              diagnostics={"returncode": getattr(proc, "returncode", None),
                                           "account_key_seen": account_seen})


def _all_providers() -> list[MacKeyProvider]:
    """First-party TraceMemo-style providers first, then the BYO helper.

    Imported lazily: ``tracememo`` reads this module's contract at import time,
    so a top-level import here would form a cycle.
    """
    from .tracememo import AppleSiliconXkeyProvider, IntelMacKeyProvider
    return [AppleSiliconXkeyProvider(), IntelMacKeyProvider(),
            ExternalHelperProvider()]


def available_providers(db_dir: str = "") -> list[tuple[MacKeyProvider, dict[str, Any]]]:
    """Return ``(provider, status)`` pairs for providers that are ready to run."""
    out = []
    for provider in _all_providers():
        try:
            status = provider.status(db_dir)
        except Exception as exc:
            status = {"name": provider.name, "available": False,
                      "reason": f"状态探测失败：{exc}"}
        if status.get("available"):
            out.append((provider, status))
    return out


def provider_statuses(db_dir: str = "") -> list[dict[str, Any]]:
    """All providers with their status, for diagnostics and the setup wizard."""
    out = []
    for provider in _all_providers():
        try:
            out.append(provider.status(db_dir))
        except Exception as exc:
            out.append({"name": provider.name, "available": False,
                        "reason": f"状态探测失败：{exc}",
                        "first_party": getattr(provider, "first_party", False)})
    return out
