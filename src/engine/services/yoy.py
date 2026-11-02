# -*- coding: utf-8 -*-
"""Year-over-year comparison: this year vs last year for the same chat(s)."""
from __future__ import annotations

import os
import sqlite3
from collections import Counter
from datetime import datetime
from typing import Any, Optional

from engine.constants import TZ, MSG_TYPES_CN, DOW_NAMES

TYPE_VOICE = 34
TYPE_IMAGE = 3
TYPE_VIDEO = 43
TYPE_STICKER = 47


def _year_bounds(year: int) -> tuple[int, int]:
    start = int(datetime(int(year), 1, 1, tzinfo=TZ).timestamp())
    end = int(datetime(int(year) + 1, 1, 1, tzinfo=TZ).timestamp())
    return start, end


def _resolve_chat(decrypted_dir: str, tip: str) -> Optional[dict[str, Any]]:
    tip = (tip or '').strip()
    if not tip:
        return None
    from engine.services.chat import get_contacts
    contacts = get_contacts(decrypted_dir) or []
    tip_l = tip.lower()
    exact = []
    fuzzy = []
    for c in contacts:
        cid = c.get('id') or ''
        name = c.get('name') or ''
        if cid == tip or name == tip:
            exact.append(c)
        elif tip_l in cid.lower() or tip_l in name.lower():
            fuzzy.append(c)
    hit = exact[0] if exact else (fuzzy[0] if len(fuzzy) == 1 else None)
    if not hit and len(fuzzy) > 1:
        raise ValueError(
            '匹配到多个会话，请用精确 id：'
            + ', '.join((c.get('id') or '?') for c in fuzzy[:8])
        )
    if not hit:
        raise ValueError('未找到会话：%s' % tip)
    return {
        'chat_id': hit.get('id'),
        'display_name': hit.get('name') or hit.get('id'),
        'is_group': (hit.get('type') == 'group') or str(hit.get('id') or '').endswith('@chatroom'),
    }


def _empty_stats(year: int) -> dict[str, Any]:
    return {
        'year': year,
        'total': 0,
        'active_days': 0,
        'me': 0,
        'peer': 0,
        'media': 0,
        'voice': 0,
        'stickers': 0,
        'hourly': [0] * 24,
        'dow': [0] * 7,
        'monthly': [0] * 12,
        'types': [],
        'top_chats': [],
    }


def _collect_from_index(
    decrypted_dir: str,
    year: int,
    *,
    chat_id: Optional[str],
    own_wxid: Optional[str],
    top_chats_n: int = 15,
) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    try:
        from engine.services import search_index
        if not search_index.index_status(decrypted_dir).get('ready'):
            return None, '搜索索引未就绪'
        conn = search_index.open_index(decrypted_dir)
        if conn is None:
            return None, '无法打开搜索索引'
    except Exception as e:  # noqa: BLE001
        return None, str(e)

    t0, t1 = _year_bounds(year)
    own_forms = set()
    if own_wxid:
        own_forms.add(own_wxid)
        own_forms.add(str(own_wxid).split('@')[0])

    try:
        sql = (
            'SELECT chat_id, local_type, create_time, sender_username '
            'FROM msg_meta WHERE create_time >= ? AND create_time < ?'
        )
        args: list[Any] = [t0, t1]
        if chat_id:
            sql += ' AND chat_id = ?'
            args.append(chat_id)
        rows = conn.execute(sql, args)
        return _fold_rows(rows, year, own_forms, top_chats_n=top_chats_n), None
    except sqlite3.Error as e:
        return None, '索引查询失败：%s' % e
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _fold_rows(rows, year: int, own_forms: set[str], *, top_chats_n: int) -> dict[str, Any]:
    hourly = [0] * 24
    dow = [0] * 7
    monthly = [0] * 12
    types: Counter = Counter()
    chats: Counter = Counter()
    days = set()
    total = me = peer = media = voice = stickers = 0

    for chat_id, local_type, create_time, sender in rows:
        ts = int(create_time or 0)
        if not ts:
            continue
        try:
            dt = datetime.fromtimestamp(ts, tz=TZ)
        except (OSError, ValueError, OverflowError):
            continue
        total += 1
        hourly[dt.hour] += 1
        dow[dt.weekday()] += 1
        monthly[dt.month - 1] += 1
        days.add(dt.date().isoformat())
        lt = int(local_type or 0)
        base = lt & 0xFFFF if lt > 0xFFFF else lt
        types[MSG_TYPES_CN.get(base, str(base))] += 1
        if chat_id:
            chats[chat_id] += 1
        if base == TYPE_IMAGE or base == TYPE_VIDEO:
            media += 1
        elif base == TYPE_VOICE:
            voice += 1
        elif base == TYPE_STICKER:
            stickers += 1
        s = (sender or '').strip()
        if own_forms and s:
            if s in own_forms or s.split('@')[0] in own_forms:
                me += 1
            else:
                peer += 1

    type_list = [
        {'name': k, 'count': v}
        for k, v in types.most_common(12)
    ]
    top = [
        {'chat_id': cid, 'count': n}
        for cid, n in chats.most_common(top_chats_n)
    ]
    return {
        'year': year,
        'total': total,
        'active_days': len(days),
        'me': me,
        'peer': peer,
        'media': media,
        'voice': voice,
        'stickers': stickers,
        'hourly': hourly,
        'dow': dow,
        'monthly': monthly,
        'types': type_list,
        'top_chats': top,
    }


def _collect_from_messages(
    decrypted_dir: str,
    year: int,
    *,
    chat_info: dict[str, Any],
    own_wxid: Optional[str],
) -> dict[str, Any]:
    """Fallback when index missing: scan one chat via collect_messages."""
    from chat_export import collect_messages

    t0, t1 = _year_bounds(year)
    # Adapt chat_info shape for collect_messages
    info = {
        'username': chat_info['chat_id'],
        'display_name': chat_info.get('display_name') or chat_info['chat_id'],
        'is_group': chat_info.get('is_group'),
    }
    # collect_messages needs more fields from scan — try full contact from chat list
    try:
        from chat_list import scan_chats
        all_chats, _, _ = scan_chats(decrypted_dir)
        for c in all_chats or []:
            if c.get('username') == chat_info['chat_id']:
                info = c
                break
    except Exception:
        pass

    messages = collect_messages(info, start_ts=t0, end_ts=t1 - 1, keyword=None)
    own_forms = set()
    if own_wxid:
        own_forms.add(own_wxid)
        own_forms.add(str(own_wxid).split('@')[0])

    hourly = [0] * 24
    dow = [0] * 7
    monthly = [0] * 12
    types: Counter = Counter()
    days = set()
    total = me = peer = media = voice = stickers = 0

    for m in messages:
        if m.get('is_system'):
            continue
        ts = int(m.get('create_time') or 0)
        if not ts:
            continue
        try:
            dt = datetime.fromtimestamp(ts, tz=TZ)
        except (OSError, ValueError, OverflowError):
            continue
        total += 1
        hourly[dt.hour] += 1
        dow[dt.weekday()] += 1
        monthly[dt.month - 1] += 1
        days.add(dt.date().isoformat())
        tname = str(m.get('type_name') or m.get('type') or '其他')
        types[tname] += 1
        if tname in ('图片', '视频') or tname in ('3', '43'):
            media += 1
        if '语音' in tname or tname == '34':
            voice += 1
        if '表情' in tname or tname == '47':
            stickers += 1
        if m.get('is_me') or (own_forms and (m.get('sender_username') or '') in own_forms):
            me += 1
        else:
            peer += 1

    return {
        'year': year,
        'total': total,
        'active_days': len(days),
        'me': me,
        'peer': peer,
        'media': media,
        'voice': voice,
        'stickers': stickers,
        'hourly': hourly,
        'dow': dow,
        'monthly': monthly,
        'types': [{'name': k, 'count': v} for k, v in types.most_common(12)],
        'top_chats': [{
            'chat_id': chat_info['chat_id'],
            'count': total,
            'display_name': chat_info.get('display_name'),
        }] if total else [],
    }


def _pct_delta(cur: float, prev: float) -> Optional[float]:
    if prev == 0:
        return None if cur == 0 else 100.0
    return round((cur - prev) * 100.0 / prev, 1)


def _enrich_top_chats(decrypted_dir: str, stats: dict[str, Any]) -> None:
    from engine.services.chat import get_contacts
    names = {c.get('id'): c.get('name') or c.get('id') for c in (get_contacts(decrypted_dir) or [])}
    for item in stats.get('top_chats') or []:
        cid = item.get('chat_id')
        item['display_name'] = names.get(cid) or cid
        item['is_group'] = bool(str(cid or '').endswith('@chatroom'))


def build_yoy_report(
    decrypted_dir: str,
    *,
    year: Optional[int] = None,
    chat: Optional[str] = None,
    own_wxid: Optional[str] = None,
) -> dict[str, Any]:
    """Compare ``year`` vs ``year-1`` for all chats or one session."""
    if year is None:
        year = datetime.now(tz=TZ).year
    try:
        year = int(year)
    except (TypeError, ValueError):
        year = datetime.now(tz=TZ).year
    year = max(2011, min(year, 2100))
    prev_year = year - 1

    chat_info = None
    chat_id = None
    if (chat or '').strip():
        chat_info = _resolve_chat(decrypted_dir, chat)
        chat_id = chat_info['chat_id']

    warnings: list[str] = []
    source = 'index'

    cur, err = _collect_from_index(
        decrypted_dir, year, chat_id=chat_id, own_wxid=own_wxid)
    prev, err2 = _collect_from_index(
        decrypted_dir, prev_year, chat_id=chat_id, own_wxid=own_wxid)

    if cur is None or prev is None:
        if chat_info is None:
            return {
                'ok': False,
                'error': '跨年对比需要搜索索引；请先在「全局搜索」构建索引。'
                         + (('（%s）' % (err or err2)) if (err or err2) else ''),
            }
        warnings.append('索引不可用，已降级为扫描该会话消息（%s）' % (err or err2 or 'n/a'))
        source = 'messages'
        cur = _collect_from_messages(
            decrypted_dir, year, chat_info=chat_info, own_wxid=own_wxid)
        prev = _collect_from_messages(
            decrypted_dir, prev_year, chat_info=chat_info, own_wxid=own_wxid)

    _enrich_top_chats(decrypted_dir, cur)
    _enrich_top_chats(decrypted_dir, prev)

    metrics = [
        ('total', '消息总数'),
        ('active_days', '活跃天数'),
        ('me', '我发送'),
        ('peer', '对方/他人'),
        ('media', '图片+视频'),
        ('voice', '语音'),
        ('stickers', '表情'),
    ]
    deltas = []
    for key, label in metrics:
        a = int(cur.get(key) or 0)
        b = int(prev.get(key) or 0)
        deltas.append({
            'key': key,
            'label': label,
            'current': a,
            'previous': b,
            'delta': a - b,
            'pct': _pct_delta(a, b),
        })

    # Merge type names for side-by-side
    type_names = []
    seen = set()
    for lst in (cur.get('types') or [], prev.get('types') or []):
        for t in lst:
            n = t.get('name')
            if n and n not in seen:
                seen.add(n)
                type_names.append(n)
    type_cmp = []
    cur_map = {t['name']: t['count'] for t in (cur.get('types') or [])}
    prev_map = {t['name']: t['count'] for t in (prev.get('types') or [])}
    for n in type_names[:12]:
        type_cmp.append({
            'name': n,
            'current': int(cur_map.get(n) or 0),
            'previous': int(prev_map.get(n) or 0),
        })

    return {
        'ok': True,
        'year': year,
        'prev_year': prev_year,
        'chat': chat_info,
        'current': cur,
        'previous': prev,
        'deltas': deltas,
        'types': type_cmp,
        'dow_labels': list(DOW_NAMES) if DOW_NAMES else ['一', '二', '三', '四', '五', '六', '日'],
        'source': source,
        'warnings': warnings,
    }
