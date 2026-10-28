# -*- coding: utf-8 -*-
"""Topic / event timeline: cluster search hits into event cards by keyword + time gap.

Does not mutate backups. Relies on the global search stack (index or fallback).
"""
from __future__ import annotations

import hashlib
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Optional

from engine.services.search import SearchIndexError, search_messages

DEFAULT_GAP_HOURS = 72
DEFAULT_MAX_PER_KEYWORD = 3000
MAX_SAMPLES = 5
MAX_CHATS_SHOWN = 8
MAX_KEYWORDS = 20


def parse_keywords(raw: str) -> list[str]:
    """Split user input into unique keywords (order preserved)."""
    text = (raw or '').strip()
    if not text:
        return []
    parts = re.split(r'[,，;；|/\n\r\t]+', text)
    out: list[str] = []
    seen = set()
    for p in parts:
        k = p.strip()
        if not k or k in seen:
            continue
        if len(k) > 64:
            k = k[:64]
        seen.add(k)
        out.append(k)
        if len(out) >= MAX_KEYWORDS:
            break
    return out


def _quote_filter_value(value: str) -> str:
    v = (value or '').strip()
    if not v:
        return '""'
    if re.search(r'[\s,:"\'|]', v):
        return '"' + v.replace('"', '') + '"'
    return v


def build_search_query(
    keyword: str,
    *,
    date_start: Optional[str] = None,
    date_end: Optional[str] = None,
    chat: Optional[str] = None,
) -> str:
    """Compose a search query string using existing 日期:/会话: syntax."""
    parts = [keyword]
    ds = (date_start or '').strip()
    de = (date_end or '').strip()
    if ds and de:
        parts.append(f'日期:{ds}..{de}')
    elif ds:
        parts.append(f'日期:{ds}..2099-12-31')
    elif de:
        parts.append(f'日期:1970-01-01..{de}')
    chat = (chat or '').strip()
    if chat:
        parts.append(f'会话:{_quote_filter_value(chat)}')
    return ' '.join(parts)


def _hit_key(hit: dict[str, Any]) -> tuple:
    return (hit.get('chat_id') or '', hit.get('local_id'))


def _cluster_by_gap(hits: list[dict[str, Any]], gap_seconds: int) -> list[list[dict[str, Any]]]:
    if not hits:
        return []
    ordered = sorted(hits, key=lambda h: (h.get('create_time') or 0, h.get('local_id') or 0))
    clusters: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = [ordered[0]]
    for hit in ordered[1:]:
        prev_ts = current[-1].get('create_time') or 0
        ts = hit.get('create_time') or 0
        if gap_seconds > 0 and (ts - prev_ts) > gap_seconds:
            clusters.append(current)
            current = [hit]
        else:
            current.append(hit)
    clusters.append(current)
    return clusters


def _fmt_ts(ts: Optional[int]) -> str:
    if not ts:
        return ''
    try:
        return datetime.fromtimestamp(int(ts)).strftime('%Y-%m-%d %H:%M')
    except (OSError, OverflowError, ValueError):
        return str(ts)


def _fmt_day(ts: Optional[int]) -> str:
    if not ts:
        return ''
    try:
        return datetime.fromtimestamp(int(ts)).strftime('%Y-%m-%d')
    except (OSError, OverflowError, ValueError):
        return ''


def _card_id(keyword: str, start_ts: int, end_ts: int, count: int) -> str:
    raw = f'{keyword}|{start_ts}|{end_ts}|{count}'
    return hashlib.md5(raw.encode('utf-8', errors='replace')).hexdigest()[:12]


def make_event_card(
    keyword: str,
    cluster: list[dict[str, Any]],
    *,
    extra_keywords: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Build one event card from a time-clustered hit list."""
    times = [int(h.get('create_time') or 0) for h in cluster if h.get('create_time')]
    start_ts = min(times) if times else 0
    end_ts = max(times) if times else 0

    chat_counter: Counter = Counter()
    chat_names: dict[str, str] = {}
    sender_counter: Counter = Counter()
    day_counter: Counter = Counter()
    for h in cluster:
        cid = h.get('chat_id') or ''
        chat_counter[cid] += 1
        chat_names[cid] = h.get('chat_display_name') or cid
        sender = h.get('sender_display_name') or h.get('sender_username') or ''
        if sender:
            sender_counter[sender] += 1
        day = _fmt_day(h.get('create_time'))
        if day:
            day_counter[day] += 1

    chats = [
        {
            'chat_id': cid,
            'display_name': chat_names.get(cid) or cid,
            'count': n,
            'is_group': bool(cid.endswith('@chatroom')),
        }
        for cid, n in chat_counter.most_common(MAX_CHATS_SHOWN)
    ]
    participants = [
        {'name': name, 'count': n}
        for name, n in sender_counter.most_common(8)
    ]
    peak_day, peak_day_count = (day_counter.most_common(1)[0]
                                if day_counter else ('', 0))

    # Prefer mid-cluster samples for a readable story
    samples = []
    step = max(1, len(cluster) // MAX_SAMPLES)
    for i in range(0, len(cluster), step):
        h = cluster[i]
        samples.append({
            'create_time': h.get('create_time'),
            'time_label': _fmt_ts(h.get('create_time')),
            'chat_display_name': h.get('chat_display_name') or h.get('chat_id'),
            'sender_display_name': h.get('sender_display_name') or h.get('sender_username'),
            'snippet': h.get('snippet') or '',
            'chat_id': h.get('chat_id'),
            'local_id': h.get('local_id'),
        })
        if len(samples) >= MAX_SAMPLES:
            break

    kws = [keyword] + [k for k in (extra_keywords or []) if k and k != keyword]
    title = keyword
    if len(kws) > 1:
        title = ' · '.join(kws[:3]) + ('…' if len(kws) > 3 else '')

    span_days = 0
    if start_ts and end_ts:
        span_days = max(0, (end_ts - start_ts) // 86400)

    return {
        'id': _card_id(keyword, start_ts, end_ts, len(cluster)),
        'title': title,
        'keywords': kws,
        'start_ts': start_ts,
        'end_ts': end_ts,
        'start_label': _fmt_ts(start_ts),
        'end_label': _fmt_ts(end_ts),
        'span_days': span_days,
        'message_count': len(cluster),
        'chat_count': len(chat_counter),
        'chats': chats,
        'participants': participants,
        'peak_day': peak_day,
        'peak_day_count': peak_day_count,
        'samples': samples,
    }


def _ranges_overlap(a: dict[str, Any], b: dict[str, Any], slack: int = 3600) -> bool:
    return not (a['end_ts'] + slack < b['start_ts'] or b['end_ts'] + slack < a['start_ts'])


def _merge_cards(cards: list[dict[str, Any]], hit_sets: list[set]) -> list[dict[str, Any]]:
    """Merge overlapping cards that share ≥1 message or ≥1 chat + time overlap."""
    if len(cards) <= 1:
        return cards

    n = len(cards)
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[rj] = ri

    for i in range(n):
        for j in range(i + 1, n):
            if not _ranges_overlap(cards[i], cards[j]):
                continue
            shared_msg = bool(hit_sets[i] & hit_sets[j])
            chats_i = {c['chat_id'] for c in cards[i].get('chats') or []}
            chats_j = {c['chat_id'] for c in cards[j].get('chats') or []}
            shared_chat = bool(chats_i & chats_j)
            # Same keyword already clustered; merge across keywords when related
            if shared_msg or shared_chat:
                union(i, j)

    groups: dict[int, list[int]] = defaultdict(list)
    for i in range(n):
        groups[find(i)].append(i)

    merged: list[dict[str, Any]] = []
    for idxs in groups.values():
        if len(idxs) == 1:
            merged.append(cards[idxs[0]])
            continue
        # Rebuild from combined keywords + earliest/latest + max counts (approx)
        kws: list[str] = []
        for i in idxs:
            for k in cards[i].get('keywords') or []:
                if k not in kws:
                    kws.append(k)
        # Prefer the densest card as base, then refresh title/keywords
        base_i = max(idxs, key=lambda i: cards[i].get('message_count') or 0)
        base = dict(cards[base_i])
        start_ts = min(cards[i]['start_ts'] for i in idxs)
        end_ts = max(cards[i]['end_ts'] for i in idxs)
        msg_count = sum(cards[i].get('message_count') or 0 for i in idxs)
        # Deduplicate chats
        chat_map: dict[str, dict] = {}
        for i in idxs:
            for c in cards[i].get('chats') or []:
                cid = c.get('chat_id') or ''
                if cid not in chat_map:
                    chat_map[cid] = dict(c)
                else:
                    chat_map[cid]['count'] = (chat_map[cid].get('count') or 0) + (c.get('count') or 0)
        chats = sorted(chat_map.values(), key=lambda x: x.get('count') or 0, reverse=True)[:MAX_CHATS_SHOWN]
        samples = []
        seen_s = set()
        for i in idxs:
            for s in cards[i].get('samples') or []:
                key = (s.get('chat_id'), s.get('local_id'))
                if key in seen_s:
                    continue
                seen_s.add(key)
                samples.append(s)
                if len(samples) >= MAX_SAMPLES:
                    break
            if len(samples) >= MAX_SAMPLES:
                break
        samples.sort(key=lambda s: s.get('create_time') or 0)
        title = ' · '.join(kws[:3]) + ('…' if len(kws) > 3 else '')
        base.update({
            'id': _card_id('|'.join(kws), start_ts, end_ts, msg_count),
            'title': title or base.get('title'),
            'keywords': kws,
            'start_ts': start_ts,
            'end_ts': end_ts,
            'start_label': _fmt_ts(start_ts),
            'end_label': _fmt_ts(end_ts),
            'span_days': max(0, (end_ts - start_ts) // 86400) if start_ts and end_ts else 0,
            'message_count': msg_count,
            'chat_count': len(chat_map),
            'chats': chats,
            'samples': samples,
        })
        merged.append(base)
    return merged


def build_event_timeline(
    decrypted_dir: str,
    keywords: list[str] | str,
    *,
    gap_hours: float = DEFAULT_GAP_HOURS,
    date_start: Optional[str] = None,
    date_end: Optional[str] = None,
    chat: Optional[str] = None,
    max_per_keyword: int = DEFAULT_MAX_PER_KEYWORD,
    merge_related: bool = True,
    own_wxid: Optional[str] = None,
) -> dict[str, Any]:
    """Search each keyword and cluster hits into event cards.

    Returns:
      ok, events, keywords, gap_hours, warnings, stats, errors
    """
    if isinstance(keywords, str):
        keywords = parse_keywords(keywords)
    else:
        keywords = parse_keywords(','.join(keywords or []))

    if not keywords:
        return {
            'ok': False,
            'error': '请至少填写一个关键词',
            'events': [],
            'keywords': [],
        }

    try:
        gap_hours = float(gap_hours)
    except (TypeError, ValueError):
        gap_hours = DEFAULT_GAP_HOURS
    gap_hours = max(1.0, min(gap_hours, 24 * 60))  # 1h .. 60d
    gap_seconds = int(gap_hours * 3600)

    try:
        max_per_keyword = int(max_per_keyword)
    except (TypeError, ValueError):
        max_per_keyword = DEFAULT_MAX_PER_KEYWORD
    max_per_keyword = max(50, min(max_per_keyword, 20000))

    cards: list[dict[str, Any]] = []
    hit_sets: list[set] = []
    warnings: list[str] = []
    errors: list[dict[str, str]] = []
    total_hits = 0
    per_kw: list[dict[str, Any]] = []

    for kw in keywords:
        q = build_search_query(kw, date_start=date_start, date_end=date_end, chat=chat)
        try:
            body = search_messages(
                decrypted_dir,
                q,
                sort='time_asc',
                export_all=True,
                include_full_text=False,
                max_retained=max_per_keyword,
                own_wxid=own_wxid,
            )
        except ValueError as e:
            errors.append({'keyword': kw, 'error': str(e)})
            continue
        except SearchIndexError as e:
            errors.append({'keyword': kw, 'error': e.as_dict().get('error') or str(e)})
            continue
        except Exception as e:  # noqa: BLE001 — surface per-keyword failures
            errors.append({'keyword': kw, 'error': '%s: %s' % (type(e).__name__, e)})
            continue

        for w in body.get('warnings') or []:
            if w not in warnings:
                warnings.append(w)
        hits = body.get('results') or []
        total_hits += len(hits)
        per_kw.append({
            'keyword': kw,
            'hits': len(hits),
            'truncated': bool(body.get('truncated')),
            'total': body.get('total'),
            'query': q,
        })
        if body.get('truncated'):
            warnings.append(
                '关键词「%s」命中超过保留上限（%s），仅用前 %s 条做聚类'
                % (kw, body.get('total'), body.get('retained_rows'))
            )

        for cluster in _cluster_by_gap(hits, gap_seconds):
            card = make_event_card(kw, cluster)
            cards.append(card)
            hit_sets.append({_hit_key(h) for h in cluster})

    if merge_related and cards:
        cards = _merge_cards(cards, hit_sets)

    cards.sort(key=lambda c: (c.get('start_ts') or 0, c.get('title') or ''), reverse=True)

    return {
        'ok': True,
        'events': cards,
        'keywords': keywords,
        'gap_hours': gap_hours,
        'date_start': date_start or '',
        'date_end': date_end or '',
        'chat': chat or '',
        'warnings': warnings,
        'errors': errors,
        'stats': {
            'keyword_count': len(keywords),
            'event_count': len(cards),
            'hit_count': total_hits,
            'per_keyword': per_kw,
            'generated_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        },
    }
