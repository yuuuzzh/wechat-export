# -*- coding: utf-8 -*-
"""Event timeline: keyword parse, gap clustering, API."""
from __future__ import annotations

import os
import sys

ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(ROOT, 'src'))

from engine.services import events as ev  # noqa: E402


def test_parse_keywords():
    assert ev.parse_keywords('搬家, 旅游，婚礼') == ['搬家', '旅游', '婚礼']
    assert ev.parse_keywords('a\nb|a') == ['a', 'b']
    assert ev.parse_keywords('') == []


def test_build_search_query():
    q = ev.build_search_query('搬家', date_start='2024-01-01', date_end='2024-12-31', chat='家人群')
    assert '搬家' in q
    assert '日期:2024-01-01..2024-12-31' in q
    assert '会话:' in q


def test_cluster_by_gap_and_card():
    base = 1_700_000_000
    hits = [
        {'chat_id': 'c1', 'local_id': 1, 'create_time': base,
         'chat_display_name': '家人群', 'sender_display_name': '甲',
         'snippet': '开始搬家'},
        {'chat_id': 'c1', 'local_id': 2, 'create_time': base + 3600,
         'chat_display_name': '家人群', 'sender_display_name': '乙',
         'snippet': '纸箱到了'},
        # 5 days later → new cluster when gap=72h
        {'chat_id': 'c2', 'local_id': 3, 'create_time': base + 5 * 86400,
         'chat_display_name': '同事', 'sender_display_name': '丙',
         'snippet': '又要搬？'},
    ]
    clusters = ev._cluster_by_gap(hits, gap_seconds=72 * 3600)
    assert len(clusters) == 2
    assert len(clusters[0]) == 2
    card = ev.make_event_card('搬家', clusters[0])
    assert card['title'] == '搬家'
    assert card['message_count'] == 2
    assert card['chat_count'] == 1
    assert card['samples']
    assert card['search_href'].startswith('/search?q=')
    assert card['samples'][0]['chat_href'].startswith('/chat?open=')


def test_build_timeline_mocked(monkeypatch, tmp_path):
    def fake_search(decrypted_dir, q, **kwargs):
        # Two keywords → different hit sets
        kw = q.split()[0]
        t0 = 1_700_000_000
        if kw == '旅游':
            results = [
                {'chat_id': 'g1', 'local_id': 1, 'create_time': t0,
                 'chat_display_name': '好友', 'sender_display_name': '我',
                 'snippet': '订机票'},
                {'chat_id': 'g1', 'local_id': 2, 'create_time': t0 + 86400,
                 'chat_display_name': '好友', 'sender_display_name': '对方',
                 'snippet': '酒店确认'},
            ]
        else:
            results = [
                {'chat_id': 'g1', 'local_id': 10, 'create_time': t0 + 12 * 3600,
                 'chat_display_name': '好友', 'sender_display_name': '我',
                 'snippet': '护照带了吗'},
            ]
        return {
            'results': results,
            'total': len(results),
            'truncated': False,
            'retained_rows': len(results),
            'warnings': [],
        }

    monkeypatch.setattr(ev, 'search_messages', fake_search)
    out = ev.build_event_timeline(
        str(tmp_path),
        '旅游, 护照',
        gap_hours=72,
        merge_related=True,
    )
    assert out['ok']
    assert out['stats']['hit_count'] == 3
    # Overlapping time + same chat → ideally one merged card
    assert out['stats']['event_count'] >= 1
    assert any('旅游' in (e.get('keywords') or []) for e in out['events'])


def test_api_timeline(tmp_path, monkeypatch):
    from web.app import create_app

    def fake_search(decrypted_dir, q, **kwargs):
        return {
            'results': [{
                'chat_id': 'x', 'local_id': 1, 'create_time': 1700000000,
                'chat_display_name': '测', 'sender_display_name': '我',
                'snippet': 'hello 搬家',
            }],
            'total': 1, 'truncated': False, 'retained_rows': 1, 'warnings': [],
        }

    monkeypatch.setattr('engine.services.events.search_messages', fake_search)
    app = create_app(decrypted_dir=str(tmp_path))
    cli = app.test_client()
    r = cli.get('/events')
    assert r.status_code == 200
    assert '事件'.encode('utf-8') in r.data or b'timeline' in r.data.lower() or '关键词'.encode('utf-8') in r.data

    r = cli.post('/api/events/timeline', json={'keywords': '搬家', 'gap_hours': 48})
    j = r.get_json()
    assert r.status_code == 200
    assert j['ok']
    assert j['stats']['event_count'] == 1

    r = cli.post('/api/events/timeline', json={'keywords': ''})
    assert r.status_code == 400
