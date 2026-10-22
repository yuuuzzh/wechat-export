# -*- coding: utf-8 -*-
"""Privacy redaction for shareable / demo exports.

Masks nicknames (consistent placeholders or asterisks), China mainland
mobile numbers, and 15/18-digit ID card numbers in message bodies and
display fields — without mutating the underlying backup databases.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any, Iterable, Optional

# China mobile: 1[3-9]xxxxxxxxx
_PHONE_RE = re.compile(
    r'(?<!\d)(1(?:3\d|4[5-9]|5[0-35-9]|6[2567]|7[0-8]|8\d|9[0-35-9])\d{8})(?!\d)'
)
# 18-digit ID (optional X checksum) or legacy 15-digit
_ID18_RE = re.compile(
    r'(?<!\d)([1-9]\d{5}(?:19|20)\d{2}'
    r'(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx])(?!\d)'
)
_ID15_RE = re.compile(
    r'(?<!\d)([1-9]\d{5}\d{2}'
    r'(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3})(?!\d)'
)

_KEEP_SENDERS = {'我', '系统消息', '归属未定', 'system', 'me'}


def mask_phone(num: str) -> str:
    s = re.sub(r'\D', '', num or '')
    if len(s) == 11:
        return s[:3] + '****' + s[7:]
    if len(s) >= 7:
        return s[:3] + '****' + s[-2:]
    return '****'


def mask_id_card(num: str) -> str:
    s = (num or '').strip()
    if len(s) >= 15:
        return s[:4] + ('*' * (len(s) - 8)) + s[-4:]
    return '****'


def mask_nickname_asterisk(name: str) -> str:
    s = str(name or '').strip()
    if not s:
        return ''
    if len(s) == 1:
        return '*'
    if len(s) == 2:
        return s[0] + '*'
    return s[0] + ('*' * (len(s) - 2)) + s[-1]


def _stable_index(key: str, salt: str = '') -> int:
    h = hashlib.md5((salt + '|' + key).encode('utf-8', errors='replace')).hexdigest()
    return int(h[:8], 16)


def placeholder_for_name(name: str, *, is_group: bool = False, index: int = 0) -> str:
    """Demo-style labels: 联系人甲 / 示例群聊1."""
    if is_group:
        return f'示例群聊{index + 1}' if index else '示例群聊'
    # Cycle through 甲乙丙… then numbers
    labels = '甲乙丙丁戊己庚辛壬癸'
    if 0 <= index < len(labels):
        return f'联系人{labels[index]}'
    return f'联系人{index + 1}'


def redact_text(
    text: str,
    *,
    phones: bool = True,
    id_cards: bool = True,
) -> str:
    if not text:
        return text or ''
    out = text
    if phones:
        out = _PHONE_RE.sub(lambda m: mask_phone(m.group(1)), out)
    if id_cards:
        out = _ID18_RE.sub(lambda m: mask_id_card(m.group(1)), out)
        out = _ID15_RE.sub(lambda m: mask_id_card(m.group(1)), out)
    return out


def _is_group_name(name: str, chat_id: str = '', flagged: bool = False) -> bool:
    if flagged or (chat_id or '').endswith('@chatroom'):
        return True
    s = name or ''
    return '群' in s and len(s) >= 2


def build_name_map(
    names: Iterable[str],
    *,
    style: str = 'placeholder',
    group_hints: Optional[dict[str, bool]] = None,
) -> dict[str, str]:
    """Map original display names → redacted labels (stable within one export)."""
    group_hints = group_hints or {}
    uniq: list[str] = []
    seen = set()
    for n in names:
        s = (n or '').strip()
        if not s or s in _KEEP_SENDERS or s in seen:
            continue
        seen.add(s)
        uniq.append(s)

    # Stable order by hash so re-exports with same set are similar
    uniq.sort(key=lambda x: (_stable_index(x), x))
    person_i = 0
    group_i = 0
    out: dict[str, str] = {}
    for name in uniq:
        is_g = bool(group_hints.get(name))
        if style == 'asterisk':
            out[name] = mask_nickname_asterisk(name)
        else:
            if is_g:
                out[name] = placeholder_for_name(name, is_group=True, index=group_i)
                group_i += 1
            else:
                out[name] = placeholder_for_name(name, is_group=False, index=person_i)
                person_i += 1
    return out


def redact_messages(
    messages: list[dict[str, Any]],
    *,
    nicknames: bool = True,
    phones: bool = True,
    id_cards: bool = True,
    style: str = 'placeholder',
    name_map: Optional[dict[str, str]] = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return a new message list with privacy fields redacted + stats."""
    stats = {
        'messages': len(messages or []),
        'names_mapped': 0,
        'phones': 0,
        'id_cards': 0,
        'style': style,
    }
    if not messages:
        return [], stats

    if name_map is None and nicknames:
        names = []
        hints: dict[str, bool] = {}
        for m in messages:
            for key in ('sender', 'chat_name'):
                v = (m.get(key) or '').strip()
                if v:
                    names.append(v)
                    if key == 'chat_name':
                        hints[v] = _is_group_name(
                            v, m.get('chat_id') or '', bool(m.get('is_group')))
        name_map = build_name_map(names, style=style, group_hints=hints)
    name_map = name_map or {}
    stats['names_mapped'] = len(name_map)

    out: list[dict[str, Any]] = []
    for m in messages:
        nm = dict(m)
        if nicknames:
            for key in ('sender', 'chat_name'):
                v = (nm.get(key) or '').strip()
                if v and v not in _KEEP_SENDERS and v in name_map:
                    nm[key] = name_map[v]
        if phones or id_cards:
            text = nm.get('text')
            if isinstance(text, str) and text:
                before = text
                after = redact_text(text, phones=phones, id_cards=id_cards)
                if after != before:
                    # rough counts
                    if phones:
                        stats['phones'] += len(_PHONE_RE.findall(before))
                    if id_cards:
                        stats['id_cards'] += (
                            len(_ID18_RE.findall(before)) + len(_ID15_RE.findall(before))
                        )
                    nm['text'] = after
        out.append(nm)
    return out, stats


def parse_privacy_options(data: Optional[dict]) -> Optional[dict[str, Any]]:
    """Parse request body flags into redact kwargs, or None if disabled."""
    if not data:
        return None
    enabled = data.get('privacy_redact')
    truthy = enabled not in (None, False, 0, '0', 'false', 'False', 'off', '')
    if not truthy:
        return None
    opts = data.get('privacy') if isinstance(data.get('privacy'), dict) else {}
    style = (opts.get('style') or data.get('privacy_style') or 'placeholder')
    if style not in ('placeholder', 'asterisk'):
        style = 'placeholder'
    return {
        'nicknames': bool(opts.get('nicknames', True)),
        'phones': bool(opts.get('phones', True)),
        'id_cards': bool(opts.get('id_cards', True)),
        'style': style,
    }
