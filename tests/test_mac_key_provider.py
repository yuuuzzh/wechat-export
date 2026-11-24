# -*- coding: utf-8 -*-
"""macOS key-source layer: contract, HMAC gating, platform isolation, guards.

No test here needs a real WeChat install or a real helper binary.
"""
from __future__ import annotations

import contextlib
import hashlib
import hmac as hmac_mod
import json
import os
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from engine.db_key_crypto import PAGE_SZ, verify_enc_key  # noqa: E402
from engine.services.mac_key import (  # noqa: E402
    KeyCandidate,
    ProviderResult,
    diagnostics,
    mask_key,
    parse_helper_output,
)
from engine.services.mac_key import adapter, providers  # noqa: E402
from engine.services.mac_key.contract import (  # noqa: E402
    ACCOUNT_KEY_REQUIRED,
    HELPER_HASH_MISMATCH,
    HELPER_NOT_CONFIGURED,
    HELPER_TIMEOUT,
)

K1 = "11" * 32
K2 = "22" * 32
S1 = "aa" * 16
S2 = "bb" * 16


def _make_page1(key_hex: str, salt_hex: str) -> bytes:
    """Build a page whose HMAC matches ``verify_enc_key`` (real crypto, no mocks)."""
    key = bytes.fromhex(key_hex)
    salt = bytes.fromhex(salt_hex)
    page = bytearray(PAGE_SZ)
    page[:16] = salt
    for i in range(16, PAGE_SZ - 80 + 16):
        page[i] = (i * 7) & 0xFF
    mac_salt = bytes(b ^ 0x3A for b in salt)
    mac_key = hashlib.pbkdf2_hmac("sha512", key, mac_salt, 2, dklen=32)
    hm = hmac_mod.new(mac_key, bytes(page[16: PAGE_SZ - 80 + 16]), hashlib.sha512)
    hm.update(struct.pack("<I", 1))
    page[PAGE_SZ - 64: PAGE_SZ] = hm.digest()
    return bytes(page)


def _db_files():
    return [
        ("message/message_0.db", "/fake/message_0.db", PAGE_SZ, S1, _make_page1(K1, S1)),
        ("contact/contact.db", "/fake/contact.db", PAGE_SZ, S2, _make_page1(K2, S2)),
    ]


def _completed(stdout: str, stderr: str = "", code: int = 0):
    return subprocess.CompletedProcess(args=[], returncode=code,
                                       stdout=stdout, stderr=stderr)


@contextlib.contextmanager
def _helper_file():
    """Real executable file, without pytest's tmp_path fixture (sandbox-safe)."""
    with tempfile.TemporaryDirectory(prefix="mac_key_test_") as tmp:
        helper = Path(tmp) / "helper"
        helper.write_text("#!/bin/sh\ntrue\n")
        helper.chmod(0o755)
        yield str(helper)


class _FakeProvider:
    def __init__(self, result: ProviderResult):
        self.name = "fake"
        self.result = result
        self.calls = 0

    def extract(self, db_dir, print_fn=print):
        self.calls += 1
        return self.result


# --------------------------------------------------------------------------
#  Contract
# --------------------------------------------------------------------------
def test_page1_fixture_is_cryptographically_valid():
    assert verify_enc_key(bytes.fromhex(K1), _make_page1(K1, S1)) is True
    assert verify_enc_key(bytes.fromhex(K2), _make_page1(K1, S1)) is False


def test_parse_tracememo_style_embedded_json():
    text = ('[*] debugger attached\n'
            + json.dumps({"success": True, "key": K1.upper(), "keyKind": "db",
                          "profile": "wechat-4.1.13"}) + '\n[done]\n')
    candidates, account, error = parse_helper_output(text)
    assert error == ""
    assert account is False
    assert len(candidates) == 1
    assert candidates[0].key_hex == K1
    assert candidates[0].profile == "wechat-4.1.13"


def test_parse_keys_array_and_0x_prefix():
    text = json.dumps({"success": True, "profile": "v1", "keys": [
        {"key": "0x" + K1, "salt": S1},
        {"key": K2, "db": "message/message_0.db"},
        {"key": K2},  # duplicate -> dropped
    ]})
    candidates, _, _ = parse_helper_output(text)
    assert [c.key_hex for c in candidates] == [K1, K2]
    assert candidates[0].salt_hex == S1
    assert candidates[1].db_rel == "message/message_0.db"


def test_parse_rejects_invalid_hex_and_reports_failure():
    candidates, _, error = parse_helper_output(
        '{"success":true,"key":"zz"}\n'
        '{"success":false,"result":"ERROR:ATTACH_FAILED: need root"}')
    assert candidates == []
    assert "ATTACH_FAILED" in error


def test_account_master_key_becomes_an_hmac_candidate():
    """TraceMemo's 4.1.13 helper returns keyKind=account; it must be tried."""
    candidates, account_seen, _ = parse_helper_output(
        json.dumps({"success": True, "key": K1, "keyKind": "account"}))
    assert account_seen is True
    assert len(candidates) == 1
    assert candidates[0].kind == "account"
    assert candidates[0].key_hex == K1


def test_mask_key_never_leaks_full_key():
    shown = mask_key(K1)
    assert K1 not in shown and shown.startswith("1111") and shown.endswith("1111")


# --------------------------------------------------------------------------
#  ExternalHelperProvider guards
# --------------------------------------------------------------------------
def test_helper_not_configured():
    p = providers.ExternalHelperProvider(environ={})
    result = p.extract("/tmp/db_storage", lambda _m: None)
    assert result.ok is False and result.code == HELPER_NOT_CONFIGURED
    assert "不捆绑" in result.message


def test_helper_sha256_mismatch_blocks_execution():
    with _helper_file() as helper:
        def must_not_run(*_a, **_kw):
            raise AssertionError("helper must not be executed on hash mismatch")

        env = {
            providers.ENV_HELPER_PATH: helper,
            providers.ENV_HELPER_SHA256: "0" * 64,
        }
        p = providers.ExternalHelperProvider(environ=env, runner=must_not_run)
        assert p.status()["reason"] == HELPER_HASH_MISMATCH
        assert p.extract("/tmp/db", lambda _m: None).code == HELPER_HASH_MISMATCH


def test_helper_runs_without_shell_and_parses_stdout():
    with _helper_file() as helper:
        seen = {}

        def runner(cmd, **kwargs):
            seen["cmd"] = cmd
            seen["kwargs"] = kwargs
            return _completed(json.dumps({"success": True, "key": K1}))

        db_dir = os.path.dirname(helper)
        env = {providers.ENV_HELPER_PATH: helper}
        result = providers.ExternalHelperProvider(environ=env, runner=runner).extract(
            db_dir, lambda _m: None)
        assert result.ok is True and len(result.candidates) == 1
        assert seen["cmd"][0] == helper
        assert "--db-dir" in seen["cmd"] and db_dir in seen["cmd"]
        assert seen["kwargs"]["shell"] is False
        assert seen["kwargs"]["timeout"] > 0


def test_helper_timeout_is_reported():
    with _helper_file() as helper:
        def timed_out(*_a, **_kw):
            raise subprocess.TimeoutExpired(cmd="helper", timeout=1)

        p = providers.ExternalHelperProvider(
            environ={providers.ENV_HELPER_PATH: helper}, runner=timed_out)
        result = p.extract("/tmp/db", lambda _m: None)
        assert result.code == HELPER_TIMEOUT
        assert "重试" in result.message


def test_helper_account_key_is_passed_to_hmac_gate():
    with _helper_file() as helper:
        def runner(*_a, **_kw):
            return _completed(json.dumps({"success": True, "key": K1,
                                         "keyKind": "account"}))

        p = providers.ExternalHelperProvider(
            environ={providers.ENV_HELPER_PATH: helper}, runner=runner)
        result = p.extract("/tmp/db", lambda _m: None)
        assert result.ok is True
        assert result.candidates[0].kind == "account"


# --------------------------------------------------------------------------
#  Adapter: HMAC is the only gate into key_map
# --------------------------------------------------------------------------
def test_adapter_only_accepts_hmac_verified_candidate(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    fake = _FakeProvider(ProviderResult(
        True, "OK", "", (KeyCandidate(K1), KeyCandidate("33" * 32)), provider="fake"))
    monkeypatch.setattr(adapter, "available_providers", lambda _d: [(fake, {})])

    key_map = {}
    logs = []
    found = adapter.extract_keys_via_mac_provider(
        "/tmp/db", _db_files(), {S1: ["a"], S2: ["b"]}, key_map,
        logs.append, lambda _p, _m: None)
    assert found == 1
    assert key_map == {S1: K1}
    assert all(K1 not in line and "33" * 32 not in line for line in logs)
    assert any("MacKey-HIT" in line for line in logs)


def test_adapter_without_provider_gives_actionable_guidance(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(adapter, "available_providers", lambda _d: [])
    monkeypatch.setattr(adapter, "provider_statuses", lambda _d: [
        {"name": "external-helper", "available": False, "reason": "未配置"}])
    logs = []
    key_map = {}
    assert adapter.extract_keys_via_mac_provider(
        "/tmp/db", _db_files(), {S1: ["a"], S2: ["b"]}, key_map, logs.append) == 0
    assert key_map == {}
    assert any("手动输入密钥" in line for line in logs)


def test_adapter_is_noop_on_windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")

    def must_not_run(*_a, **_kw):
        raise AssertionError("macOS provider must not be consulted on Windows")

    monkeypatch.setattr(adapter, "available_providers", must_not_run)
    assert adapter.extract_keys_via_mac_provider(
        "/tmp/db", _db_files(), {S1: ["a"]}, {}, lambda _m: None) == 0


def test_macos_strategy_chain_needs_no_windll_and_never_raises_on_no_keys(monkeypatch):
    from engine.services import wechat_key_extract as wke

    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(wke, "load_from_config",
                        lambda *_a, **_kw: 0)  # ignore any real local config
    monkeypatch.setattr(adapter, "available_providers", lambda _d: [])
    monkeypatch.setattr(adapter, "provider_statuses", lambda _d: [
        {"name": "external-helper", "available": False, "reason": "未配置"}])

    with tempfile.TemporaryDirectory(prefix="mac_key_chain_") as tmp:
        db_dir = Path(tmp) / "db_storage"
        (db_dir / "message").mkdir(parents=True)
        (db_dir / "message" / "message_0.db").write_bytes(_make_page1(K1, S1))

        logs = []
        result = wke._extract_all_keys_macos(
            str(db_dir), logs.append, lambda _p, _m: None,
            use_mmkv=False, use_mac_provider=True)
        assert result == {}
        assert any("手动输入密钥" in line for line in logs)
        assert not any("No keys extracted" in line for line in logs)


# --------------------------------------------------------------------------
#  Static safety guards + diagnostics
# --------------------------------------------------------------------------
def test_byo_provider_source_has_no_hidden_privilege_escalation():
    """The generic BYO helper stays unprivileged; the TraceMemo port is explicit."""
    src = Path(providers.__file__).read_text(encoding="utf-8")
    assert "shell=False" in src
    for forbidden in ("osascript", "sudo ", "task_for_pid", "DYLD_INSERT_LIBRARIES",
                      "csrutil disable"):
        assert forbidden not in src, f"forbidden in provider source: {forbidden}"
    from engine.services.mac_key import tracememo
    tm_src = Path(tracememo.__file__).read_text(encoding="utf-8")
    assert "with administrator privileges" in tm_src  # explicit, user-confirmed prompt


def test_recommendations_explain_advanced_mode_prerequisites():
    info = {
        "system": "macos", "auto_extract_ready": True,
        "sip_enabled": True, "mac_key_flow": "apple-silicon",
        "wechat_version": "4.2.0",
    }
    lines = diagnostics.recommendations(info)
    text = "\n".join(lines)
    assert "手动输入密钥" in text
    assert "关闭 SIP" in text and "重新开启" in text
    assert "4.1.13" in text  # compatibility warning for 4.2.0
    assert "HMAC" in text


def test_capabilities_exposes_mac_key_snapshot():
    from engine.platform_info import capabilities
    assert isinstance(capabilities().get("mac_key"), dict)
