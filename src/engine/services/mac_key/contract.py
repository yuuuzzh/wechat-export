# -*- coding: utf-8 -*-
"""macOS key-helper output contract (v1).

Design goals
------------
* **Provider-neutral**: the main program never cares how a key was obtained.
  A helper is an external process that prints JSON lines on stdout.
* **Compatible with the ecosystem**: accepts the shape used by TraceMemo's
  ``xkey_helper`` (``{"success":true,"key":"<64hex>","keyKind":"db"}``),
  including JSON embedded in log text.
* **Strict**: every candidate must pass the SQLCipher page-1 HMAC check
  before it is allowed into ``key_map``. A helper cannot inject a bad key.
* **Private**: keys are never logged; :func:`mask_key` is the only display form.

This module is platform-neutral and has no Win32 / Flask imports so macOS and
Linux can import it freely.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

KEY_HEX_RE = re.compile(r"^[0-9a-fA-F]{64}$")
SALT_HEX_RE = re.compile(r"^[0-9a-fA-F]{32}$")

# Error codes are part of the public contract: UI text and tests key off them.
HELPER_NOT_CONFIGURED = "HELPER_NOT_CONFIGURED"
HELPER_NOT_EXECUTABLE = "HELPER_NOT_EXECUTABLE"
HELPER_HASH_MISMATCH = "HELPER_HASH_MISMATCH"
HELPER_TIMEOUT = "HELPER_TIMEOUT"
HELPER_OUTPUT_INVALID = "HELPER_OUTPUT_INVALID"
HELPER_FAILED = "HELPER_FAILED"
ACCOUNT_KEY_REQUIRED = "ACCOUNT_KEY_DERIVATION_REQUIRED"
NO_VERIFIED_KEY = "NO_VERIFIED_KEY"
MMKV_FORMAT_UNSUPPORTED = "MMKV_FORMAT_UNSUPPORTED"
NOT_MACOS = "NOT_MACOS"

MAX_OUTPUT_BYTES = 1_048_576  # 1 MiB of stdout/stderr, hard cap


@dataclass(frozen=True)
class KeyCandidate:
    """One 32-byte SQLCipher key proposed by a helper.

    ``salt_hex`` / ``db_rel`` are optional hints. When absent the adapter tries
    the candidate against every unresolved salt (HMAC decides).
    """

    key_hex: str
    salt_hex: str = ""
    db_rel: str = ""
    profile: str = ""
    kind: str = "db"  # "db" (per-database) or "account" (master key)

    def __post_init__(self) -> None:
        if not KEY_HEX_RE.match(self.key_hex):
            raise ValueError("key must be 64 hex chars")
        if self.salt_hex and not SALT_HEX_RE.match(self.salt_hex):
            raise ValueError("salt must be 32 hex chars")


@dataclass(frozen=True)
class ProviderResult:
    ok: bool
    code: str
    message: str
    candidates: tuple[KeyCandidate, ...] = ()
    provider: str = ""
    diagnostics: dict[str, Any] = field(default_factory=dict)


def mask_key(key_hex: str) -> str:
    """Safe display form. Never return the full key to a log/UI surface."""
    if not key_hex or len(key_hex) < 12:
        return "****"
    return f"{key_hex[:4]}…{key_hex[-4:]}"


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def parse_helper_output(text: str) -> tuple[list[KeyCandidate], bool, str]:
    """Parse helper stdout into candidates.

    Returns ``(candidates, account_key_seen, error_message)``.
    ``account_key_seen`` marks the ``keyKind=account`` / ``master`` case.
    TraceMemo's 4.1.13 helper returns exactly that shape, so account keys ARE
    returned as candidates: the adapter tries them against every database
    page-1 HMAC first. If none verify, a PBKDF2 derivation layer may still be
    needed — the adapter reports that hint instead of faking success.
    """
    candidates: list[KeyCandidate] = []
    seen: set[str] = set()
    account_seen = False
    errors: list[str] = []

    if not text or len(text.encode("utf-8", "replace")) > MAX_OUTPUT_BYTES:
        return [], False, HELPER_OUTPUT_INVALID

    decoder = json.JSONDecoder()
    cursor = 0
    length = len(text)
    while cursor < length:
        start = text.find("{", cursor)
        if start < 0:
            break
        try:
            obj, end = decoder.raw_decode(text, start)
        except ValueError:
            cursor = start + 1
            continue
        cursor = end if end > start else start + 1
        if not isinstance(obj, dict):
            continue

        if obj.get("success") is not True:
            detail = str(obj.get("result") or obj.get("error") or obj.get("code") or "")
            if detail:
                errors.append(detail[:160])
            continue

        kind = str(obj.get("keyKind") or obj.get("kind") or "db").lower()
        if obj.get("master") is True or kind == "account":
            account_seen = True
        profile = str(obj.get("profile") or "")

        raw_items: list[dict[str, Any]] = []
        entries = obj.get("keys")
        if isinstance(entries, list):
            raw_items.extend(_as_dict(e) for e in entries)
        if obj.get("key") is not None:
            raw_items.append({
                "key": obj.get("key"),
                "salt": obj.get("salt"),
                "db": obj.get("db") or obj.get("rel"),
                "profile": profile,
                "kind": kind,
            })

        for item in raw_items:
            key_hex = str(item.get("key") or "").strip().removeprefix("0x").removeprefix("0X")
            if not KEY_HEX_RE.match(key_hex):
                continue
            key_hex = key_hex.lower()
            salt_hex = str(item.get("salt") or "").strip().lower()
            if salt_hex and not SALT_HEX_RE.match(salt_hex):
                salt_hex = ""
            item_kind = str(item.get("kind") or kind).lower()
            if item_kind == "account" or obj.get("master") is True:
                account_seen = True
            if key_hex in seen:
                continue
            seen.add(key_hex)
            candidates.append(KeyCandidate(
                key_hex=key_hex,
                salt_hex=salt_hex,
                db_rel=str(item.get("db") or ""),
                profile=str(item.get("profile") or profile),
                kind="account" if item_kind == "account" else "db",
            ))

    error = "; ".join(errors[:3]) if errors else ""
    return candidates, account_seen, error
