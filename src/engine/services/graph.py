# -*- coding: utf-8 -*-
"""Read-only relationship graph: friend / group interaction intensity.

Ego-centric: center = self, spokes = chats weighted by message count.
Optional: top senders inside top groups (requires search index).
"""
from __future__ import annotations

import math
import os
import sqlite3
from datetime import datetime
from typing import Any, Optional
from urllib.parse import quote

from engine.services.chat import get_contacts

SELF_ID = '__self__'
DEFAULT_TOP_N = 40
DEFAULT_MIN_MESSAGES = 3
MAX_TOP_N = 200
MAX_MEMBER_GROUPS = 12
DEFAULT_MEMBER_TOP = 5


def _parse_day_start(s: Optional[str]) -> Optional[int]:
    s = (s or '').strip()
    if not s:
        return None
    try:
        return int(datetime.strptime(s[:10], '%Y-%m-%d').timestamp())
    except ValueError:
        return None


def _parse_day_end(s: Optional[str]) -> Optional[int]:
    """Inclusive end date → exclusive next-day timestamp."""
    s = (s or '').strip()
    if not s:
        return None
    try:
        day = datetime.strptime(s[:10], '%Y-%m-%d')
        return int(day.timestamp()) + 86400
    except ValueError:
        return None


def _find_chats_db(decrypted_dir: str) -> Optional[str]:
    for p in (
        os.path.join(decrypted_dir, 'data', 'chats.db'),
        os.path.join(decrypted_dir, 'chats.db'),
    ):
        if os.path.isfile(p):
            return p
    return None


def _index_counts(
    decrypted_dir: str,
    *,
    t0: Optional[int],
    t1: Optional[int],
) -> tuple[Optional[dict[str, int]], Optional[str]]:
    """Per-chat message counts from search index; (None, reason) if unavailable."""
    try:
        from engine.services import search_index
        status = search_index.index_status(decrypted_dir)
        if not status.get('ready'):
            return None, '搜索索引未就绪，已用 chats.db 全量计数（无法按日期过滤）'
        conn = search_index.open_index(decrypted_dir)
        if conn is None:
            return None, '无法打开搜索索引'
    except Exception as e:  # noqa: BLE001
        return None, '搜索索引不可用：%s' % e

    try:
        sql = 'SELECT chat_id, COUNT(*) FROM msg_meta WHERE 1=1'
        args: list[Any] = []
        if t0 is not None:
            sql += ' AND create_time >= ?'
            args.append(int(t0))
        if t1 is not None:
            sql += ' AND create_time < ?'
            args.append(int(t1))
        sql += ' GROUP BY chat_id'
        rows = conn.execute(sql, args).fetchall()
        return {str(cid): int(n or 0) for cid, n in rows if cid}, None
    except sqlite3.Error as e:
        return None, '索引统计失败：%s' % e
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _top_group_senders(
    decrypted_dir: str,
    group_ids: list[str],
    *,
    t0: Optional[int],
    t1: Optional[int],
    per_group: int,
    own_forms: set[str],
) -> dict[str, list[tuple[str, int]]]:
    """group_id → [(sender_username, count), ...]"""
    out: dict[str, list[tuple[str, int]]] = {g: [] for g in group_ids}
    if not group_ids:
        return out
    try:
        from engine.services import search_index
        if not search_index.index_status(decrypted_dir).get('ready'):
            return out
        conn = search_index.open_index(decrypted_dir)
        if conn is None:
            return out
    except Exception:
        return out

    try:
        for gid in group_ids:
            sql = (
                'SELECT sender_username, COUNT(*) AS c FROM msg_meta '
                'WHERE chat_id = ? AND sender_username IS NOT NULL '
                'AND sender_username != \'\''
            )
            args: list[Any] = [gid]
            if t0 is not None:
                sql += ' AND create_time >= ?'
                args.append(int(t0))
            if t1 is not None:
                sql += ' AND create_time < ?'
                args.append(int(t1))
            sql += ' GROUP BY sender_username ORDER BY c DESC LIMIT ?'
            args.append(int(per_group) + len(own_forms) + 2)
            rows = conn.execute(sql, args).fetchall()
            kept = []
            for sender, n in rows:
                s = (sender or '').strip()
                if not s or s in own_forms:
                    continue
                kept.append((s, int(n or 0)))
                if len(kept) >= per_group:
                    break
            out[gid] = kept
    except sqlite3.Error:
        pass
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return out


def _symbol_size(value: int, vmin: int, vmax: int, lo: int = 18, hi: int = 64) -> int:
    if vmax <= vmin:
        return (lo + hi) // 2
    t = (value - vmin) / float(vmax - vmin)
    # Ease so mid-tier nodes stay readable
    t = math.sqrt(max(0.0, min(1.0, t)))
    return int(lo + t * (hi - lo))


def _display_map(contacts: list[dict]) -> dict[str, str]:
    return {
        (c.get('id') or ''): (c.get('name') or c.get('id') or '')
        for c in contacts if c.get('id')
    }


def build_relation_graph(
    decrypted_dir: str,
    *,
    kind: str = 'all',
    top_n: int = DEFAULT_TOP_N,
    min_messages: int = DEFAULT_MIN_MESSAGES,
    date_start: Optional[str] = None,
    date_end: Optional[str] = None,
    include_members: bool = False,
    member_top: int = DEFAULT_MEMBER_TOP,
    own_wxid: Optional[str] = None,
) -> dict[str, Any]:
    """Build ECharts-ready graph payload (nodes + links). Read-only."""
    kind = (kind or 'all').strip().lower()
    if kind not in ('all', 'friends', 'groups'):
        kind = 'all'
    try:
        top_n = max(1, min(int(top_n), MAX_TOP_N))
    except (TypeError, ValueError):
        top_n = DEFAULT_TOP_N
    try:
        min_messages = max(1, min(int(min_messages), 100000))
    except (TypeError, ValueError):
        min_messages = DEFAULT_MIN_MESSAGES
    try:
        member_top = max(1, min(int(member_top), 20))
    except (TypeError, ValueError):
        member_top = DEFAULT_MEMBER_TOP

    t0 = _parse_day_start(date_start)
    t1 = _parse_day_end(date_end)
    warnings: list[str] = []

    contacts = get_contacts(decrypted_dir, wxid=own_wxid) or []
    names = _display_map(contacts)

    # Own forms to skip
    own_forms = set()
    if own_wxid:
        own_forms.add(own_wxid)
        if not str(own_wxid).endswith('@chatroom'):
            bare = str(own_wxid).split('@')[0]
            own_forms.add(bare)

    need_date = bool(t0 is not None or t1 is not None)
    counts: Optional[dict[str, int]] = None
    if need_date:
        counts, warn = _index_counts(decrypted_dir, t0=t0, t1=t1)
        if warn:
            warnings.append(warn)
        if counts is None:
            warnings.append('日期过滤需要已构建的搜索索引；本次回退为全量互动强度')

    rows: list[dict[str, Any]] = []
    for c in contacts:
        cid = c.get('id') or ''
        if not cid or cid in own_forms:
            continue
        is_group = (c.get('type') == 'group') or cid.endswith('@chatroom')
        is_official = (not is_group) and cid.startswith('gh_')
        if kind == 'friends' and (is_group or is_official):
            continue
        if kind == 'groups' and not is_group:
            continue
        if is_official and kind == 'all':
            # Keep gh_ out of default graph — noise
            continue
        if counts is not None:
            msg_n = int(counts.get(cid) or 0)
        else:
            msg_n = int(c.get('msg_count') or 0)
        if msg_n < min_messages:
            continue
        rows.append({
            'id': cid,
            'name': c.get('name') or names.get(cid) or cid,
            'is_group': is_group,
            'msg_count': msg_n,
            'last_msg_time': c.get('last_msg_time'),
            'avatar_url': c.get('avatar_url') or ('/api/avatar/%s' % cid),
        })

    rows.sort(key=lambda r: r['msg_count'], reverse=True)
    total_matching = len(rows)
    rows = rows[:top_n]

    if not rows and not contacts:
        hint = '未找到会话数据。请先完成一键备份并生成索引。'
        if not _find_chats_db(decrypted_dir):
            hint = '缺少 data/chats.db，请先跑一遍备份/索引。'
        return {
            'ok': False,
            'error': hint,
            'nodes': [],
            'links': [],
            'categories': [],
        }

    values = [r['msg_count'] for r in rows] or [0]
    vmin, vmax = min(values), max(values)

    categories = [
        {'name': '我'},
        {'name': '好友'},
        {'name': '群聊'},
        {'name': '群成员'},
    ]
    nodes = [{
        'id': SELF_ID,
        'name': '我',
        'category': 0,
        'value': vmax or 1,
        'symbolSize': 72,
        'itemStyle': {'color': '#3d9b72'},
        'label': {'fontWeight': 'bold'},
    }]
    links = []

    for r in rows:
        cat = 2 if r['is_group'] else 1
        nodes.append({
            'id': r['id'],
            'name': r['name'],
            'category': cat,
            'value': r['msg_count'],
            'symbolSize': _symbol_size(r['msg_count'], vmin, vmax),
            'chat_id': r['id'],
            'is_group': r['is_group'],
            'href': '/chat?open=' + quote(r['id'], safe=''),
            'avatar_url': r.get('avatar_url'),
            'last_msg_time': r.get('last_msg_time'),
        })
        links.append({
            'source': SELF_ID,
            'target': r['id'],
            'value': r['msg_count'],
            'lineStyle': {
                'width': max(1.0, min(10.0, 1.0 + 9.0 * math.sqrt(
                    (r['msg_count'] - vmin) / float(max(1, vmax - vmin))
                ))),
                'curveness': 0.08,
            },
        })

    member_nodes_added = 0
    if include_members:
        group_rows = [r for r in rows if r['is_group']][:MAX_MEMBER_GROUPS]
        senders = _top_group_senders(
            decrypted_dir,
            [r['id'] for r in group_rows],
            t0=t0, t1=t1,
            per_group=member_top,
            own_forms=own_forms,
        )
        # Resolve display names for senders via contact list
        seen_members: set[str] = set()
        for gr in group_rows:
            for sender, cnt in senders.get(gr['id']) or []:
                mid = 'member:' + sender
                if sender not in seen_members:
                    seen_members.add(sender)
                    nodes.append({
                        'id': mid,
                        'name': names.get(sender) or sender,
                        'category': 3,
                        'value': cnt,
                        'symbolSize': _symbol_size(cnt, 1, max(vmax, cnt), lo=12, hi=36),
                        'wxid': sender,
                        'href': ('/chat?open=' + quote(sender, safe='')) if sender in names else '',
                    })
                    member_nodes_added += 1
                links.append({
                    'source': gr['id'],
                    'target': mid,
                    'value': cnt,
                    'lineStyle': {
                        'width': max(0.8, min(4.0, cnt / 50.0)),
                        'type': 'dashed',
                        'opacity': 0.55,
                        'curveness': 0.15,
                    },
                })

    return {
        'ok': True,
        'nodes': nodes,
        'links': links,
        'categories': categories,
        'warnings': warnings,
        'stats': {
            'shown': len(rows),
            'matching': total_matching,
            'top_n': top_n,
            'min_messages': min_messages,
            'kind': kind,
            'date_start': (date_start or '').strip()[:10],
            'date_end': (date_end or '').strip()[:10],
            'include_members': bool(include_members),
            'member_nodes': member_nodes_added,
            'max_messages': vmax,
            'source': 'index' if counts is not None else 'chats.db',
            'chats_db': bool(_find_chats_db(decrypted_dir)),
        },
        'ranking': [
            {
                'id': r['id'],
                'name': r['name'],
                'is_group': r['is_group'],
                'msg_count': r['msg_count'],
                'href': '/chat?open=' + quote(r['id'], safe=''),
            }
            for r in rows
        ],
    }
