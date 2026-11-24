# -*- coding: utf-8 -*-
"""TraceMemo-style macOS key flow: parity, failure codes, HMAC gate, UI wiring.

Everything is synthetic: no real WeChat process, no SIP change, no helper
binary and no administrator prompt is ever triggered by these tests.
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
PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

from engine.db_key_crypto import PAGE_SZ  # noqa: E402
from engine.services.mac_key import adapter, tracememo as tm  # noqa: E402
from engine.services.mac_key.contract import KeyCandidate, ProviderResult  # noqa: E402

K1 = "11" * 32
S1 = "aa" * 16


def _read(rel: str) -> str:
    return (Path(PROJECT) / rel).read_text(encoding='utf-8')


@contextlib.contextmanager
def _helper_file():
    with tempfile.TemporaryDirectory(prefix='tm_helper_test_') as tmp:
        helper = Path(tmp) / 'xkey_helper'
        helper.write_text('#!/bin/sh\ntrue\n')
        helper.chmod(0o755)
        yield str(helper)


def _completed(stdout: str, stderr: str = '', code: int = 0):
    return subprocess.CompletedProcess(args=[], returncode=code,
                                       stdout=stdout, stderr=stderr)


def _page1(key_hex: str, salt_hex: str) -> bytes:
    salt = bytes.fromhex(salt_hex)
    page = bytearray(PAGE_SZ)
    page[:16] = salt
    mac_salt = bytes(b ^ 0x3A for b in salt)
    mac_key = hashlib.pbkdf2_hmac('sha512', bytes.fromhex(key_hex),
                                  mac_salt, 2, dklen=32)
    hm = hmac_mod.new(mac_key, bytes(page[16: PAGE_SZ - 80 + 16]), hashlib.sha512)
    hm.update(struct.pack('<I', 1))
    page[PAGE_SZ - 64: PAGE_SZ] = hm.digest()
    return bytes(page)


class _FakeProvider:
    def __init__(self, result):
        self.name = 'fake-tm'
        self.result = result

    def extract(self, db_dir, print_fn=print):
        return self.result


# --------------------------------------------------------------------------
#  Architecture decisions (same truth table as shared/macos-arch.ts)
# --------------------------------------------------------------------------
def test_resolve_mac_key_flow_truth_table():
    assert tm.resolve_mac_key_flow('win32', 'unknown', 'x64', False) == 'unsupported'
    assert tm.resolve_mac_key_flow('darwin', 'arm64', 'arm64', False) == 'apple-silicon'
    assert tm.resolve_mac_key_flow('darwin', 'arm64', 'x64', True) == 'arch-mismatch'
    assert tm.resolve_mac_key_flow('darwin', 'arm64', 'x64', False) == 'arch-mismatch'
    assert tm.resolve_mac_key_flow('darwin', 'x64', 'x64', False) == 'intel'
    assert tm.resolve_mac_key_flow('darwin', 'unknown', 'x64', False) == 'intel'


def test_parse_sip_enabled():
    assert tm.parse_sip_enabled('System Integrity Protection status: enabled.') is True
    assert tm.parse_sip_enabled('System Integrity Protection status: disabled.') is False
    assert tm.parse_sip_enabled('') is False


# --------------------------------------------------------------------------
#  Profile dispatch
# --------------------------------------------------------------------------
def test_helper_mode_only_matches_4113():
    assert tm.resolve_xkey_helper_mode('4.1.13.8') == 'wechat-4.1.13'
    assert tm.resolve_xkey_helper_mode('4.1.13') == 'wechat-4.1.13'
    assert tm.resolve_xkey_helper_mode('4.1.130') == 'legacy'
    assert tm.resolve_xkey_helper_mode('4.2.0') == 'legacy'
    assert tm.resolve_xkey_helper_mode('') == 'legacy'


def test_invocation_413_uses_dedicated_helper_and_account_flag():
    inv = tm.build_apple_silicon_invocation('4.1.13.8', 4321, 60_000)
    assert inv['mode'] == 'wechat-4.1.13'
    assert inv['resource_name'] == tm.HELPER_413
    assert inv['args'] == ['4321', '120000', '--profile',
                           'wechat-4.1.13', '--account']
    assert inv['timeout_seconds'] > 120


def test_invocation_legacy_uses_plain_pid_timeout():
    inv = tm.build_apple_silicon_invocation('4.2.0', 99, 60_000)
    assert inv['mode'] == 'legacy'
    assert inv['resource_name'] == tm.HELPER_LEGACY
    assert inv['args'] == ['99', '60000']


# --------------------------------------------------------------------------
#  Failure mapping + output parsing
# --------------------------------------------------------------------------
def test_failure_codes_are_actionable():
    assert tm.map_xkey_helper_failure(
        'ERROR:CAPTURE_TIMEOUT:timeout waiting for breakpoint hit').code == 'CAPTURE_TIMEOUT'
    sink = tm.map_xkey_helper_failure(
        'ERROR:SCAN_FAILED:Sink pattern not found')
    assert sink.code == 'SCAN_FAILED' and '4.1.8' in sink.message
    assert tm.map_xkey_helper_failure('permission denied').code == 'PERMISSION_DENIED'
    assert tm.map_xkey_helper_failure('').code == tm.HELPER_RESULT_INVALID


def test_parse_success_payload_embedded_in_log():
    out = ('[*] debugger attached\n'
           + json.dumps({'success': True, 'key': '0x' + K1.upper(),
                         'keyKind': 'db', 'profile': 'wechat-4.1.13'})
           + '\n[done]')
    result = tm.parse_xkey_helper_output(out)
    assert result.ok and len(result.candidates) == 1
    assert result.candidates[0].key_hex == K1
    assert result.candidates[0].profile == 'wechat-4.1.13'


def test_parse_account_key_is_accepted_as_candidate():
    result = tm.parse_xkey_helper_output(
        json.dumps({'success': True, 'key': K1, 'keyKind': 'account'}))
    assert result.ok
    assert result.candidates[0].kind == 'account'


def test_parse_failure_payload():
    result = tm.parse_xkey_helper_output(
        json.dumps({'success': False, 'result': 'ERROR:SCAN_FAILED:Sink pattern not found'}))
    assert result.code == 'SCAN_FAILED'


# --------------------------------------------------------------------------
#  Apple Silicon provider
# --------------------------------------------------------------------------
def _patch_apple_silicon(monkeypatch, helper='', sip=False, version='4.1.13.8'):
    monkeypatch.setattr(tm, 'get_mac_arch_snapshot', lambda: {
        'platform': 'darwin', 'hardware_arch': 'arm64', 'runtime_arch': 'arm64',
        'under_translation': False, 'mac_key_flow': 'apple-silicon'})
    monkeypatch.setattr(tm, 'detect_wechat_version', lambda: version)
    monkeypatch.setattr(tm, 'get_wechat_pid', lambda: 4321)
    monkeypatch.setattr(tm, 'is_sip_enabled', lambda: sip)
    monkeypatch.setattr(tm, 'find_helper', lambda _name: helper)


def test_status_requires_helper_but_not_sip_disabled(monkeypatch):
    with _helper_file() as helper:
        _patch_apple_silicon(monkeypatch, helper=helper, sip=True)
        status = tm.AppleSiliconXkeyProvider().status('/tmp/db')
        assert status['available'] is True
        assert status['sip_enabled'] is True
        assert status['mode'] == 'wechat-4.1.13'


def test_extract_blocks_when_sip_enabled(monkeypatch):
    with _helper_file() as helper:
        _patch_apple_silicon(monkeypatch, helper=helper, sip=True)
        result = tm.AppleSiliconXkeyProvider().extract('/tmp/db', lambda _m: None)
        assert result.code == tm.SIP_ENABLED
        assert 'csrutil disable' in result.message


def test_extract_blocks_arch_mismatch_first(monkeypatch):
    monkeypatch.setattr(tm, 'get_mac_arch_snapshot', lambda: {
        'mac_key_flow': 'arch-mismatch'})
    result = tm.AppleSiliconXkeyProvider().extract('/tmp/db', lambda _m: None)
    assert result.code == tm.ARCH_MISMATCH_X64_ON_ARM


def test_extract_reports_missing_helper(monkeypatch):
    _patch_apple_silicon(monkeypatch, helper='')
    result = tm.AppleSiliconXkeyProvider().extract('/tmp/db', lambda _m: None)
    assert result.code == tm.HELPER_NOT_FOUND


def test_extract_success_via_osascript(monkeypatch):
    with _helper_file() as helper:
        _patch_apple_silicon(monkeypatch, helper=helper)
        seen = {}

        def runner(argv, **kwargs):
            seen['argv'] = argv
            seen['kwargs'] = kwargs
            return _completed('OK::' + json.dumps(
                {'success': True, 'key': K1, 'keyKind': 'account',
                 'profile': 'wechat-4.1.13'}))

        result = tm.AppleSiliconXkeyProvider(runner=runner).extract(
            '/tmp/db', lambda _m: None)
        assert result.ok and result.candidates[0].key_hex == K1
        assert seen['argv'][0] == '/usr/bin/osascript'
        blob = '\n'.join(seen['argv'])
        assert 'with administrator privileges' in blob
        assert 'quoted form of helperPath' in blob
        assert '--profile' in blob and '4321' in blob
        assert seen['kwargs']['shell'] is False


def test_extract_handles_cancelled_authorization(monkeypatch):
    with _helper_file() as helper:
        _patch_apple_silicon(monkeypatch, helper=helper)
        result = tm.AppleSiliconXkeyProvider(
            runner=lambda *_a, **_kw: _completed('ERR::-128::User canceled')).extract(
            '/tmp/db', lambda _m: None)
        assert result.code == tm.AUTH_CANCELLED


def test_extract_handles_wechat_not_running(monkeypatch):
    with _helper_file() as helper:
        _patch_apple_silicon(monkeypatch, helper=helper)
        monkeypatch.setattr(tm, 'get_wechat_pid',
                            lambda: (_ for _ in ()).throw(RuntimeError('none')))
        result = tm.AppleSiliconXkeyProvider().extract('/tmp/db', lambda _m: None)
        assert result.code == tm.WECHAT_NOT_RUNNING


# --------------------------------------------------------------------------
#  Intel JSONL provider
# --------------------------------------------------------------------------
def test_intel_provider_parses_jsonl_result(monkeypatch):
    with _helper_file() as helper:
        monkeypatch.setattr(tm, 'get_mac_arch_snapshot',
                            lambda: {'mac_key_flow': 'intel'})
        monkeypatch.setattr(tm, 'find_helper', lambda _name: helper)
        monkeypatch.setattr(tm, 'is_sip_enabled', lambda: False)
        stdout = '\n'.join([
            json.dumps({'type': 'progress', 'message': '连接组件已就绪'}),
            json.dumps({'type': 'result', 'success': True, 'key': K1}),
        ])
        logs = []
        result = tm.IntelMacKeyProvider(
            runner=lambda *_a, **_kw: _completed(stdout)).extract(
            '/tmp/xwechat_files/account/db_storage', logs.append)
        assert result.ok and result.candidates[0].key_hex == K1
        assert any('连接组件' in line for line in logs)


# --------------------------------------------------------------------------
#  HMAC is still the only gate (account-level key from 4.1.13 helper)
# --------------------------------------------------------------------------
def test_adapter_verifies_account_key_against_every_salt(monkeypatch):
    monkeypatch.setattr(sys, 'platform', 'darwin')
    s2 = 'bb' * 16
    db_files = [
        ('message/message_0.db', '/fake/a.db', PAGE_SZ, S1, _page1(K1, S1)),
        ('contact/contact.db', '/fake/b.db', PAGE_SZ, s2, _page1(K1, s2)),
    ]
    fake = _FakeProvider(ProviderResult(
        True, 'OK', '', (KeyCandidate(K1, kind='account'),), provider='fake-tm'))
    monkeypatch.setattr(adapter, 'available_providers', lambda _d: [(fake, {})])
    key_map = {}
    found = adapter.extract_keys_via_mac_provider(
        '/tmp/db', db_files, {S1: ['a'], s2: ['b']}, key_map,
        lambda _m: None)
    assert found == 2
    assert key_map == {S1: K1, s2: K1}


# --------------------------------------------------------------------------
#  Static wiring contracts
# --------------------------------------------------------------------------
def test_user_guide_and_prepare_script_exist():
    guide = _read('docs/mac-auto-key.md')
    assert 'csrutil disable' in guide and 'SCAN_FAILED' in guide
    script = _read('scripts/prepare_mac_key_helper.sh')
    assert 'codesign --force --sign -' in script
    assert 'LICENSE' in script or 'NOTICE' in script
    # Accepts resources dir / .app / clone root, and verifies sha256 sidecars.
    assert 'resolve_src' in script and 'shasum -a 256' in script
    assert '/Contents/Resources/resources' in script
    # Workspace-root convenience entry (the project itself lives in ./src).
    forward = (Path(PROJECT).parent / 'scripts' /
               'prepare_mac_key_helper.sh').read_text(encoding='utf-8')
    assert 'src/scripts/prepare_mac_key_helper.sh' in forward
    assert 'exec' in forward


def test_api_and_wizard_expose_advanced_mode():
    assert '/mac-keyscan' in _read('src/web/routes/backup_api.py')
    assert '_mac_keyscan_sse' in _read('src/web/routes/backup_api.py')
    assert 'mac_keys_advanced' in _read('src/web/routes/setup_api.py')
    page = _read('src/web/templates/keyscan.html')
    assert 'mac-keyscan-advanced' in page
    assert '/api/backup/mac-keyscan' in page
    assert 'keysMacAdvanced' in _read('src/web/templates/dashboard.html')
    assert 'mac_keys_advanced' in _read('src/web/templates/setup.html')


def test_docs_no_longer_claim_mac_has_no_auto_extract():
    platform = _read('docs/platform.md')
    assert '高级提钥' in platform
    readme = _read('README.md')
    assert 'docs/mac-auto-key.md' in readme


def test_platform_info_keeps_windows_gate_separate():
    src = _read('src/engine/platform_info.py')
    assert 'def mac_auto_key_ready' in src
    assert 'def auto_key_extract_supported' in src
    assert 'return is_windows()' in src
