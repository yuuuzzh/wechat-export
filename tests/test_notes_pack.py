# -*- coding: utf-8 -*-
"""Notes pack: daily markdown + attachments zip."""
from __future__ import annotations

import json
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


def test_decrypt_dat_v0_to_preview(tmp_path):
    # Minimal JPEG magic XOR'd with 0xC9 (known V0 key)
    xor = 0xC9
    plain = b'\xff\xd8\xff\xe0' + b'\x00' * 32 + b'\xff\xd9'
    enc = bytes(b ^ xor for b in plain)
    dat = tmp_path / 'img.dat'
    dat.write_bytes(enc)
    # decrypted_dir only used for cache parent
    dec_dir = tmp_path / 'backup'
    dec_dir.mkdir()
    out = np._decrypt_dat_to_preview(str(dec_dir), str(dat), md5='a' * 32)
    assert out and os.path.isfile(out)
    with open(out, 'rb') as f:
        head = f.read(3)
    assert head == b'\xff\xd8\xff'


def test_materialize_decrypts_dat(tmp_path):
    xor = 0xC9
    plain = b'\xff\xd8\xff\xe0' + b'\x00' * 32 + b'\xff\xd9'
    enc = bytes(b ^ xor for b in plain)
    dat = tmp_path / 'pic.dat'
    dat.write_bytes(enc)
    dec_dir = tmp_path / 'backup'
    dec_dir.mkdir()
    attach = tmp_path / 'attach'
    msg = {
        'type': 3,
        'local_id': 9,
        'chat_id': 'room@chatroom',
        'date': '2023-11-14',
    }
    name, err = np._materialize_attachment(
        str(dec_dir), str(dat), str(attach), msg, set(), md5='a' * 32,
    )
    assert err is None
    assert name and name.endswith('.jpg')
    assert os.path.isfile(os.path.join(attach, name))
    with open(os.path.join(attach, name), 'rb') as f:
        assert f.read(3) == b'\xff\xd8\xff'


def test_build_notes_pack_manifest_and_missing(tmp_path, monkeypatch):
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
            'create_time': 1700000200,
            'timestamp': '2023-11-14 20:56:00',
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
            'local_id': 3,
            'raw': '<img md5="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"/>',
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
            'local_id': 4,
            'raw': '第二天',
        },
    ]

    def fake_collect(chat_info, **kwargs):
        assert kwargs.get('include_raw') is True
        return list(msgs)

    img = tmp_path / 'src.jpg'
    img.write_bytes(b'\xff\xd8\xff\xe0' + b'\x00' * 8)

    def fake_resolve(decrypted_dir, msg):
        if msg.get('local_id') == 2:
            return str(img), 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
        return None, 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb'

    monkeypatch.setattr('chat_export.collect_messages', fake_collect)
    monkeypatch.setattr(np, '_resolve_attachment', fake_resolve)

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
    assert result['stats']['msg_count'] == 4
    assert result['stats']['attach_count'] == 1
    assert result['stats']['missing_count'] == 1
    assert len(result['missing']) == 1
    assert result['missing'][0]['reason'] == 'not_found'

    with zipfile.ZipFile(result['zip_path']) as zf:
        names = zf.namelist()
        assert any(n.endswith('manifest.json') for n in names)
        assert any(n.endswith('missing.csv') for n in names)
        assert any(n.endswith('daily/2023-11-14.md') for n in names)
        man = json.loads(zf.read([n for n in names if n.endswith('manifest.json')][0]))
        assert man['version'] == 2
        assert man['stats']['missing_count'] == 1
        assert man['missing'][0]['md5'].startswith('bbbb')


def test_api_notes_pack_option_in_page():
    from web.app import create_app
    app = create_app(decrypted_dir=os.path.join(ROOT, 'no_such'))
    cli = app.test_client()
    r = cli.get('/export')
    assert r.status_code == 200
    assert b'notes-pack' in r.data
