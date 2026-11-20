# -*- coding: utf-8 -*-
"""Unit tests for group daily report helpers (no Flask / no backup required)."""
from __future__ import annotations

import os
import sys
from datetime import date

ROOT = os.path.join(os.path.dirname(__file__), '..', 'src')
if ROOT not in sys.path:
    sys.path.insert(0, os.path.abspath(ROOT))

from engine.services.group_report import (  # noqa: E402
    re_safe_name,
    render_group_report_html,
    resolve_date_range,
)
from engine.services.group_members import (  # noqa: E402
    extract_room_member_wxids,
    member_speaking_stats,
)


def test_resolve_date_range_presets():
    today = date(2026, 3, 15)
    s, e, label = resolve_date_range('today', today=today)
    assert s == e == today and label == '今日'

    s, e, label = resolve_date_range('yesterday', today=today)
    assert s == e == date(2026, 3, 14) and label == '昨日'

    s, e, label = resolve_date_range('7d', today=today)
    assert s == date(2026, 3, 9) and e == today and '7' in label

    s, e, label = resolve_date_range(
        'custom', start_date='2026-01-01', end_date='2026-01-10', today=today)
    assert s == date(2026, 1, 1) and e == date(2026, 1, 10)


def test_extract_room_member_wxids():
    blob = b'xx\x00wxid_abcdef123456\x00foo\x00wxid_zzzzzzzzzzzz\x00gh_official\x00'
    ids = extract_room_member_wxids(blob)
    assert 'wxid_abcdef123456' in ids
    assert 'wxid_zzzzzzzzzzzz' in ids
    assert all(not x.startswith('gh_') for x in ids)


def test_render_group_report_html_contains_title():
    report = {
        'display_name': '示例群聊',
        'chat_id': '123@chatroom',
        'range_label': '昨日',
        'start_date': '2026-03-14',
        'end_date': '2026-03-14',
        'generated_at': '2026-03-15T10:00:00+08:00',
        'overview': {
            'total_messages': 12,
            'unique_speakers': 3,
            'active_days': 1,
            'messages_per_day': 12,
            'media_count': 1,
            'voice_count': 0,
            'peak_hour': 21,
            'peak_weekday': '周六',
        },
        'members': [{'name': '甲', 'count': 8, 'share': 0.66}],
        'types': [{'name': '文本', 'count': 10}],
        'keywords': [{'word': '开会', 'count': 3, 'weight': 1.0}],
        'highlights': [{'time': '03-14 21:00', 'sender': '甲', 'text': '明天开会'}],
        'speaking': {
            'silent_members': [{'display_name': '乙'}],
            'limitations': ['测试限制说明'],
        },
        'note': '本地统计',
    }
    html = render_group_report_html(report)
    assert '示例群聊' in html
    assert '沉默成员' in html
    assert '开会' in html
    assert '测试限制说明' in html


def test_re_safe_name():
    assert '/' not in re_safe_name('a/b:c')
    assert re_safe_name('') == 'group'


def test_member_speaking_stats_with_fake_roster(monkeypatch=None):
    # Lightweight: call with empty decrypted dir → message_sample/empty path
    # without crashing.
    result = member_speaking_stats(
        decrypted_dir='/tmp/wechat-export-no-such-dir',
        chatroom_id='999@chatroom',
        speaker_counts={'甲': 5, '乙': 0},
    )
    assert 'active_members' in result
    assert 'silent_members' in result
    assert isinstance(result['limitations'], list)
