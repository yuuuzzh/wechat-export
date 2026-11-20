# -*- coding: utf-8 -*-
"""Platform-neutral helpers must import without Win32 / Flask."""
from __future__ import annotations

import os
import sys
import tempfile

ROOT = os.path.join(os.path.dirname(__file__), '..', 'src')
if ROOT not in sys.path:
    sys.path.insert(0, os.path.abspath(ROOT))

from engine.db_key_crypto import collect_db_files, verify_enc_key, PAGE_SZ  # noqa: E402
from engine.platform_info import (  # noqa: E402
    capabilities,
    is_macos,
    is_windows,
    mac_wechat_roots,
    system_name,
)


def test_verify_enc_key_rejects_short_page():
    assert verify_enc_key(b'\x00' * 32, b'\x00' * 10) is False


def test_collect_db_files_empty_dir():
    with tempfile.TemporaryDirectory() as d:
        files, salts = collect_db_files(d)
        assert files == []
        assert salts == {}


def test_collect_db_files_skips_tiny():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, 'tiny.db')
        with open(path, 'wb') as f:
            f.write(b'x' * 100)
        files, _ = collect_db_files(d)
        assert files == []


def test_capabilities_shape():
    caps = capabilities()
    assert caps['system'] in ('windows', 'macos', 'linux') or caps['system']
    assert 'auto_key_extract' in caps
    assert caps['manual_keys'] is True
    assert isinstance(caps['notes'], list)


def test_mac_roots_are_absolute():
    for p in mac_wechat_roots():
        assert p.startswith(os.path.expanduser('~')) or p.startswith('/')


def test_system_flags_consistent():
    name = system_name()
    if name == 'windows':
        assert is_windows() and not is_macos()
    elif name == 'macos':
        assert is_macos() and not is_windows()
