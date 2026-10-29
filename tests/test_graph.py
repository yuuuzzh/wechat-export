# -*- coding: utf-8 -*-
"""Relationship graph: intensity ranking + API."""
from __future__ import annotations

import os
import sys

ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(ROOT, 'src'))

from engine.services import graph as g  # noqa: E402


def _fake_contacts():
    return [
        {'id': 'wxid_a', 'name': 'Alice', 'type': 'user', 'msg_count': 100,
         'last_msg_time': 1700000000, 'avatar_url': '/api/avatar/wxid_a'},
        {'id': 'wxid_b', 'name': 'Bob', 'type': 'user', 'msg_count': 50,
         'last_msg_time': 1700000100, 'avatar_url': '/api/avatar/wxid_b'},
        {'id': 'room1@chatroom', 'name': '家人群', 'type': 'group', 'msg_count': 200,
         'last_msg_time': 1700000200, 'avatar_url': '/api/avatar/room1@chatroom'},
        {'id': 'gh_news', 'name': '某公众号', 'type': 'user', 'msg_count': 999,
         'last_msg_time': 1700000300, 'avatar_url': '/api/avatar/gh_news'},
        {'id': 'wxid_low', 'name': '很少聊', 'type': 'user', 'msg_count': 1,
         'last_msg_time': 1700000400, 'avatar_url': '/api/avatar/wxid_low'},
    ]


def test_build_relation_graph_basic(monkeypatch, tmp_path):
    monkeypatch.setattr(g, 'get_contacts', lambda *a, **k: _fake_contacts())
    monkeypatch.setattr(g, '_index_counts', lambda *a, **k: (None, None))

    out = g.build_relation_graph(str(tmp_path), min_messages=3, top_n=10)
    assert out['ok']
    ids = {n['id'] for n in out['nodes']}
    assert g.SELF_ID in ids
    assert 'wxid_a' in ids
    assert 'room1@chatroom' in ids
    assert 'gh_news' not in ids  # official filtered in all
    assert 'wxid_low' not in ids  # below min_messages
    # Ego edges only (no members)
    assert all(L['source'] == g.SELF_ID for L in out['links'])
    assert out['stats']['shown'] == 3
    assert out['ranking'][0]['id'] == 'room1@chatroom'


def test_kind_friends_and_top_n(monkeypatch, tmp_path):
    monkeypatch.setattr(g, 'get_contacts', lambda *a, **k: _fake_contacts())
    monkeypatch.setattr(g, '_index_counts', lambda *a, **k: (None, None))

    out = g.build_relation_graph(str(tmp_path), kind='friends', min_messages=1, top_n=1)
    assert out['ok']
    chat_nodes = [n for n in out['nodes'] if n['id'] != g.SELF_ID]
    assert len(chat_nodes) == 1
    assert chat_nodes[0]['id'] == 'wxid_a'
    assert not chat_nodes[0].get('is_group')


def test_api_graph(monkeypatch, tmp_path):
    from web.app import create_app

    monkeypatch.setattr(
        'engine.services.graph.get_contacts',
        lambda *a, **k: _fake_contacts(),
    )
    monkeypatch.setattr(
        'engine.services.graph._index_counts',
        lambda *a, **k: (None, None),
    )

    app = create_app(decrypted_dir=str(tmp_path))
    cli = app.test_client()
    r = cli.get('/graph')
    assert r.status_code == 200
    assert '关系图谱'.encode('utf-8') in r.data

    r = cli.post('/api/graph/relation', json={'kind': 'all', 'min_messages': 3})
    j = r.get_json()
    assert r.status_code == 200
    assert j['ok']
    assert j['nodes']
    assert j['links']
