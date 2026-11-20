# -*- coding: utf-8 -*-
"""Group member roster + speaking / silent stats.

TraceMemo-inspired, adapted to wechat-export's offline backup model:

* Prefer member wxids parsed from ``contact.db`` / ``chat_room.ext_buffer``
  (closer to a real roster than sampling message senders).
* Fall back to historical message senders when the roster blob is empty.
* Always attach ``limitations`` — silent-member conclusions are only as good
  as the roster source.
"""
from __future__ import annotations

import os
import re
import sqlite3
from typing import Any, Optional

_WXID_RE = re.compile(rb'wxid_[a-z0-9]+')
_ASCII_ID_RE = re.compile(
    rb'(?:[a-zA-Z][a-zA-Z0-9_]{3,30}|[0-9]{5,20}(?:@openim)?)'
)


def extract_room_member_wxids(ext_buffer: bytes | None) -> list[str]:
    """Best-effort parse of member identifiers from chat_room.ext_buffer."""
    if not ext_buffer:
        return []
    seen: set[str] = set()
    out: list[str] = []

    def _add(raw: str) -> None:
        key = raw.strip()
        if not key or key in seen:
            return
        if key.endswith('@chatroom') or key.startswith('gh_'):
            return
        if key in ('username', 'owner', 'chatroom', 'member', 'null'):
            return
        seen.add(key)
        out.append(key)

    for m in _WXID_RE.findall(ext_buffer):
        _add(m.decode('ascii', errors='ignore'))
    for m in _ASCII_ID_RE.findall(ext_buffer):
        s = m.decode('ascii', errors='ignore')
        if s.startswith('wxid_'):
            continue
        _add(s)
    return out


def load_room_roster(decrypted_dir: str, chatroom_id: str) -> dict[str, Any]:
    """Load current-ish member roster for a group.

    Returns::
        {
          'chat_id', 'source': 'ext_buffer'|'message_sample'|'empty',
          'owner_wxid', 'members': [{wxid, display_name, is_owner}],
          'limitations': [...]
        }
    """
    from engine.services.chat import (
        _find_file,
        _load_contacts,
        _load_room_owners,
        get_group_members,
    )

    limitations: list[str] = []
    contact_db = _find_file(decrypted_dir, 'contact/contact.db', 'contact.db')
    id_to_name, name_to_id, _ = _load_contacts(contact_db)
    owners = _load_room_owners(contact_db)
    owner_wxid = owners.get(chatroom_id, '') or ''

    roster_wxids: list[str] = []
    source = 'empty'
    if contact_db and os.path.isfile(contact_db):
        try:
            conn = sqlite3.connect(contact_db)
            row = conn.execute(
                'SELECT ext_buffer FROM chat_room WHERE username=?',
                (chatroom_id,),
            ).fetchone()
            conn.close()
            blob = row[0] if row else None
            if isinstance(blob, memoryview):
                blob = bytes(blob)
            if isinstance(blob, bytes) and blob:
                roster_wxids = extract_room_member_wxids(blob)
                if roster_wxids:
                    source = 'ext_buffer'
        except sqlite3.Error:
            limitations.append('读取 contact.db / chat_room 失败，已回退。')

    members: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _display(wxid: str) -> str:
        if wxid in name_to_id:
            return id_to_name.get(name_to_id[wxid], wxid) or wxid
        return wxid

    if roster_wxids:
        for wxid in roster_wxids:
            if wxid in seen:
                continue
            seen.add(wxid)
            members.append({
                'wxid': wxid,
                'display_name': _display(wxid),
                'is_owner': wxid == owner_wxid,
            })
        limitations.append(
            '成员名单来自 contact.db 的 chat_room.ext_buffer 解析，'
            '不同微信版本字段可能不全；请与发言榜交叉核对。'
        )
    else:
        # Fallback: historical speakers sampled from messages.
        sampled = get_group_members(decrypted_dir, chatroom_id)
        source = 'message_sample' if sampled else 'empty'
        for m in sampled:
            wxid = m.get('wxid') or m.get('display_name') or ''
            if not wxid or wxid in seen:
                continue
            seen.add(wxid)
            members.append({
                'wxid': wxid,
                'display_name': m.get('display_name') or wxid,
                'is_owner': bool(m.get('is_owner')),
            })
        limitations.append(
            '未能从通讯录解析完整群成员，已用历史消息抽样发言者代替；'
            '「沉默成员」只能表示「曾发言但在本窗口未发言」，'
            '不能代表真正的当前群成员全量。'
        )

    if owner_wxid and owner_wxid not in seen:
        members.insert(0, {
            'wxid': owner_wxid,
            'display_name': _display(owner_wxid),
            'is_owner': True,
        })

    return {
        'chat_id': chatroom_id,
        'source': source,
        'owner_wxid': owner_wxid or None,
        'member_count': len(members),
        'members': members,
        'limitations': limitations,
    }


def member_speaking_stats(
    *,
    decrypted_dir: str,
    chatroom_id: str,
    speaker_counts: dict[str, int],
    speaker_by_wxid: Optional[dict[str, int]] = None,
) -> dict[str, Any]:
    """Compute active / silent members given window speaker counts.

    ``speaker_counts`` maps display_name → message count (from report builder).
    ``speaker_by_wxid`` optional map wxid → count for more reliable joins.
    """
    roster = load_room_roster(decrypted_dir, chatroom_id)
    speaker_by_wxid = speaker_by_wxid or {}

    # Index speakers by display name (case-sensitive as stored).
    name_to_count = {str(k): int(v) for k, v in (speaker_counts or {}).items() if k}

    active: list[dict[str, Any]] = []
    silent: list[dict[str, Any]] = []
    matched_names: set[str] = set()

    for m in roster['members']:
        wxid = m['wxid']
        name = m['display_name']
        count = int(speaker_by_wxid.get(wxid) or name_to_count.get(name) or 0)
        row = {
            'wxid': wxid,
            'display_name': name,
            'is_owner': m.get('is_owner', False),
            'message_count': count,
        }
        if count > 0:
            active.append(row)
            matched_names.add(name)
        else:
            silent.append(row)

    # Speakers who appeared in the window but are not in the roster
    # (former members / unresolved nicknames).
    former: list[dict[str, Any]] = []
    for name, count in sorted(name_to_count.items(), key=lambda x: -x[1]):
        if name in matched_names or name == '我':
            continue
        former.append({
            'wxid': None,
            'display_name': name,
            'is_owner': False,
            'message_count': int(count),
        })

    active.sort(key=lambda r: (-r['message_count'], r['display_name']))
    silent.sort(key=lambda r: r['display_name'])
    former.sort(key=lambda r: (-r['message_count'], r['display_name']))

    return {
        'chat_id': chatroom_id,
        'roster_source': roster['source'],
        'roster_member_count': roster['member_count'],
        'active_members': active,
        'silent_members': silent,
        'former_speakers': former,
        'active_count': len(active),
        'silent_count': len(silent),
        'limitations': list(roster['limitations']),
    }
