# -*- coding: utf-8 -*-
"""Privacy redaction for demo exports."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src'))

from engine.services.privacy_redact import (
    build_name_map,
    mask_id_card,
    mask_phone,
    parse_privacy_options,
    redact_messages,
    redact_text,
)


def test_phone_and_id_mask():
    assert mask_phone('13812345678') == '138****5678'
    assert '****' in mask_id_card('11010519900307421X')
    text = '联系我 13812345678，身份证 11010519900307421X'
    out = redact_text(text)
    assert '138****5678' in out
    assert '11010519900307421X' not in out
    assert '1101' in out


def test_nickname_placeholder_and_messages():
    msgs = [
        {'sender': '张三', 'chat_name': '家人群聊', 'chat_id': 'x@chatroom',
         'is_group': True, 'text': '我的手机 13900001111'},
        {'sender': '李四', 'chat_name': '家人群聊', 'chat_id': 'x@chatroom',
         'is_group': True, 'text': '好的'},
        {'sender': '我', 'chat_name': '家人群聊', 'text': 'ok'},
    ]
    out, stats = redact_messages(msgs, style='placeholder')
    assert stats['phones'] >= 1
    assert out[0]['sender'].startswith('联系人')
    assert out[0]['chat_name'].startswith('示例群聊')
    assert out[2]['sender'] == '我'
    assert '139****1111' in out[0]['text']


def test_parse_options():
    assert parse_privacy_options({}) is None
    assert parse_privacy_options({'privacy_redact': False}) is None
    opts = parse_privacy_options({
        'privacy_redact': True,
        'privacy': {'style': 'asterisk', 'phones': False},
    })
    assert opts['style'] == 'asterisk'
    assert opts['phones'] is False
    assert opts['nicknames'] is True


def test_name_map_group_hint():
    nmap = build_name_map(
        ['Alice', 'Bob群'],
        style='placeholder',
        group_hints={'Bob群': True},
    )
    assert '联系人' in nmap['Alice']
    assert nmap['Bob群'].startswith('示例群聊')
