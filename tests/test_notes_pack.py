# -*- coding: utf-8 -*-
"""Notes pack: daily markdown + attachments zip."""
from __future__ import annotations

import os
import sys
import zipfile

ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(ROOT, 'src'))

from engine.services import notes_pack as np  # noqa: E402


def test_extract_md5s_and_safe_name():
    raw = '<img md5="AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA" /><md5>bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb</md5>'
    md5s = np._extract_md5s(raw)
    assert len(md5s) == 2
    assert np._safe_name('家人群 / 测试') == '家人群_测试'


def test_build_notes_pack(tmp_path, monkeypatch):
    # Fake collect_messages
    msgs = [
        {
            'create_time': 1700000000,
            'timestamp': '2023-11-14 20:53:20',
            'date': '2023-11-14',
            'sender': '甲',
            'is_me': False,
            'is_system': False,
            'type': 1,
            'type_name': '文本',
            'text': '你好',
            'chat_name': '测试群',
            'chat_id': 'room@chatroom',
            'is_group': True,
            'local_id': 1,
            'raw': '你好',
        },
        {
            'create_time': 1700000100,
            'timestamp': '2023-11-14 20:55:00',
            'date': '2023-11-14',
            'sender': '我',
            'is_me': True,
            'is_system': False,
            'type': 3,
            'type_name': '图片',
            'text': '[图片]',
            'chat_name': '测试群',
            'chat_id': 'room@chatroom',
            'is_group': True,
            'local_id': 2,
            'raw': '<img md5="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"/>',
        },
        {
            'create_time': 1700086400,
            'timestamp': '2023-11-15 20:53:20',
            'date': '2023-11-15',
            'sender': '甲',
            'is_me': False,
            'is_system': False,
            'type': 1,
            'type_name': '文本',
            'text': '第二天',
            'chat_name': '测试群',
            'chat_id': 'room@chatroom',
            'is_group': True,
            'local_id': 3,
            'raw': '第二天',
        },
    ]

    def fake_collect(chat_info, **kwargs):
        assert kwargs.get('include_raw') is True
        return list(msgs)

    # Fake image file for attachment copy
    img = tmp_path / 'src.jpg'
    img.write_bytes(b'fakemarker')

    monkeypatch.setattr('chat_export.collect_messages', fake_collect)
    monkeypatch.setattr(np, '_resolve_attachment', lambda *a, **k: str(img))

    out = tmp_path / 'export'
    out.mkdir()
    chat = {
        'username': 'room@chatroom',
        'display_name': '测试群',
        'is_group': True,
        'tables': [{'db_path': 'x', 'table_name': 'Msg_x'}],
    }
    result = np.build_notes_pack(str(tmp_path), [chat], str(out))
    assert result['ok']
    zpath = result['zip_path']
    assert os.path.isfile(zpath)
    assert result['stats']['msg_count'] == 3
    assert result['stats']['day_count'] == 2
    assert result['stats']['attach_count'] >= 1

    with zipfile.ZipFile(zpath) as zf:
        names = zf.namelist()
        assert any(n.endswith('daily/2023-11-14.md') for n in names)
        assert any(n.endswith('daily/2023-11-15.md') for n in names)
        assert any(n.endswith('README.md') for n in names)
        assert any('/attachments/2023-11-14/' in n for n in names)
        day = zf.read([n for n in names if n.endswith('daily/2023-11-14.md')][0]).decode('utf-8')
        assert '你好' in day
        assert '测试群' in day


def test_api_notes_pack_option_in_page():
    from web.app import create_app
    app = create_app(decrypted_dir=os.path.join(ROOT, 'no_such'))
    cli = app.test_client()
    r = cli.get('/export')
    assert r.status_code == 200
    assert b'notes-pack' in r.data
