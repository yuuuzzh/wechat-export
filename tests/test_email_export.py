# -*- coding: utf-8 -*-
"""EML / mbox chat export writers."""
from __future__ import annotations

import mailbox
import os
import sys
import zipfile

ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(ROOT, 'src'))

from chat_export import _write_mbox, _write_eml_zip, _normalize_fmt  # noqa: E402


def _msgs():
    return [
        {
            'create_time': 1700000000,
            'timestamp': '2023-11-15 06:13:20',
            'date': '2023-11-15',
            'sender': '我',
            'is_me': True,
            'is_system': False,
            'type': 1,
            'type_name': '文本',
            'text': '你好',
            'chat_name': '测试群',
            'chat_id': '123@chatroom',
            'is_group': True,
            'local_id': 1,
        },
        {
            'create_time': 1700000100,
            'timestamp': '2023-11-15 06:15:00',
            'date': '2023-11-15',
            'sender': '张三',
            'is_me': False,
            'is_system': False,
            'type': 1,
            'type_name': '文本',
            'text': '收到 From someone',
            'chat_name': '测试群',
            'chat_id': '123@chatroom',
            'is_group': True,
            'local_id': 2,
        },
    ]


def test_normalize_email_aliases():
    assert _normalize_fmt('email') == 'eml'
    assert _normalize_fmt('mailbox') == 'mbox'


def test_write_mbox(tmp_path):
    path = str(tmp_path / 'out.mbox')
    meta = {'display': '测试群', 'uname': '123@chatroom', 'exported_at': '2026-01-01'}
    _write_mbox(path, _msgs(), meta)
    assert os.path.isfile(path)
    box = mailbox.mbox(path)
    assert len(box) == 2
    bodies = [m.get_payload(decode=True).decode('utf-8') for m in box]
    assert any('你好' in b for b in bodies)
    box.close()


def test_write_eml_zip(tmp_path):
    path = str(tmp_path / 'out.zip')
    meta = {'display': '测试群', 'uname': '123@chatroom', 'exported_at': '2026-01-01'}
    _write_eml_zip(path, _msgs(), meta)
    assert os.path.isfile(path)
    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
        assert any(n.endswith('.eml') for n in names)
        assert any(n.endswith('README.txt') for n in names)
