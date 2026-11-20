# -*- coding: utf-8 -*-
"""Date-range group daily report (deterministic, no AI).

Inspired by TraceMemo's 群聊日报 UX (today / yesterday / 7d + HTML export),
but stays local-first and model-free: stats, rankings, heatmap, keywords,
highlights, and silent-member analysis over an offline backup.
"""
from __future__ import annotations

import html
import os
from collections import Counter
from datetime import date, datetime, timedelta
from typing import Any, Optional

from engine.constants import DOW_NAMES, TZ
from engine.services.group_members import member_speaking_stats


PRESETS = ('today', 'yesterday', '7d', '30d', 'custom')


def resolve_date_range(
    preset: str = 'today',
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    *,
    today: Optional[date] = None,
) -> tuple[date, date, str]:
    """Return (start, end, label) inclusive dates in local TZ calendar days."""
    today = today or datetime.now(TZ).date()
    preset = (preset or 'today').strip().lower()
    if preset == 'yesterday':
        d = today - timedelta(days=1)
        return d, d, '昨日'
    if preset == '7d':
        return today - timedelta(days=6), today, '近 7 天'
    if preset == '30d':
        return today - timedelta(days=29), today, '近 30 天'
    if preset == 'custom':
        if not start_date or not end_date:
            raise ValueError('自定义范围需要 start_date 与 end_date（YYYY-MM-DD）')
        s = date.fromisoformat(start_date)
        e = date.fromisoformat(end_date)
        if e < s:
            s, e = e, s
        return s, e, f'{s.isoformat()} ~ {e.isoformat()}'
    # today (default)
    return today, today, '今日'


def _day_bounds(start: date, end: date) -> tuple[int, int]:
    start_ts = int(datetime(start.year, start.month, start.day, tzinfo=TZ).timestamp())
    end_exclusive = datetime(end.year, end.month, end.day, tzinfo=TZ) + timedelta(days=1)
    end_ts = int(end_exclusive.timestamp()) - 1
    return start_ts, end_ts


def resolve_group_chat(decrypted_dir: str, chat: str) -> dict[str, Any]:
    """Resolve a group chat_info dict by username or display name."""
    tip = (chat or '').strip()
    if not tip:
        raise ValueError('缺少群聊参数 chat')
    if not tip.endswith('@chatroom') and '@chatroom' not in tip:
        # allow display name; still must resolve to a group
        pass

    all_chats: list[dict] = []
    try:
        from chat_list import scan_chats
        all_chats, _, _ = scan_chats(decrypted_dir)
    except Exception:
        all_chats = []
    if not all_chats:
        try:
            from web.routes.export_api import _scan_chats_flat
            all_chats = _scan_chats_flat(decrypted_dir, tip)
        except Exception:
            all_chats = []

    tip_l = tip.lower()
    chat_info = None
    for c in all_chats or []:
        if c.get('username') == tip or c.get('display_name') == tip:
            chat_info = c
            break
    if not chat_info:
        fuzzy = [
            c for c in (all_chats or [])
            if tip_l in (c.get('display_name') or '').lower()
            or tip_l in (c.get('username') or '').lower()
        ]
        groups = [c for c in fuzzy if (c.get('username') or '').endswith('@chatroom') or c.get('is_group')]
        pool = groups or fuzzy
        if len(pool) == 1:
            chat_info = pool[0]
        elif not pool:
            raise ValueError('未找到群聊：%s' % tip)
        else:
            raise ValueError(
                '匹配到多个会话，请使用精确 username：%s'
                % ', '.join((c.get('username') or '?') for c in pool[:8])
            )

    uname = chat_info.get('username') or tip
    if not (uname.endswith('@chatroom') or chat_info.get('is_group')):
        raise ValueError('请选择群聊（当前匹配到非群会话）')
    return chat_info


def build_group_report(
    decrypted_dir: str,
    chat: str,
    *,
    preset: str = 'today',
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    highlight_limit: int = 12,
) -> dict[str, Any]:
    """Build a deterministic group daily report dict."""
    from chat_export import collect_messages

    chat_info = resolve_group_chat(decrypted_dir, chat)
    uname = chat_info.get('username') or chat
    display = chat_info.get('display_name') or uname
    start_d, end_d, label = resolve_date_range(preset, start_date, end_date)
    start_ts, end_ts = _day_bounds(start_d, end_d)

    messages = collect_messages(chat_info, start_ts=start_ts, end_ts=end_ts, keyword=None)

    hourly = Counter()
    dow = Counter()
    type_counter = Counter()
    member_counter: Counter = Counter()
    member_media: Counter = Counter()
    active_days: set[str] = set()
    texts: list[str] = []
    highlights: list[dict[str, Any]] = []
    me_count = 0
    peer_count = 0
    media = stickers = voice = 0
    matrix = [[0] * 24 for _ in range(7)]
    system_skipped = 0

    for m in messages:
        if m.get('is_system'):
            system_skipped += 1
            continue
        ts = int(m.get('create_time') or 0)
        if not ts:
            continue
        try:
            dt = datetime.fromtimestamp(ts, tz=TZ)
        except (OSError, ValueError):
            continue
        hourly[dt.hour] += 1
        dow[dt.weekday()] += 1
        active_days.add(dt.date().isoformat())
        matrix[dt.weekday()][dt.hour] += 1

        tname = str(m.get('type_name') or m.get('type') or '其他')
        type_counter[tname] += 1
        is_media = tname in ('图片', '视频', '3', '43')
        is_sticker = ('表情' in tname) or tname in ('47',)
        is_voice = tname in ('语音', '34')
        if is_media:
            media += 1
        if is_sticker:
            stickers += 1
        if is_voice:
            voice += 1

        is_me = bool(m.get('is_me'))
        content = m.get('text') or ''
        if is_me:
            me_count += 1
            member_label = '我'
        else:
            peer_count += 1
            member_label = (m.get('sender') or '未知').strip() or '未知'
        member_counter[member_label] += 1
        if is_media or is_sticker:
            member_media[member_label] += 1

        if isinstance(content, str) and content.strip() and not content.startswith('['):
            texts.append(content.strip())
            highlights.append({
                'time': dt.strftime('%m-%d %H:%M'),
                'ts': ts,
                'sender': member_label,
                'text': content.strip()[:240],
                'score': len(content.strip()),
            })

    total = me_count + peer_count
    peak_hour = hourly.most_common(1)[0][0] if hourly else None
    peak_dow = dow.most_common(1)[0][0] if dow else None
    peak_dow_name = (
        DOW_NAMES[peak_dow]
        if peak_dow is not None and 0 <= peak_dow < len(DOW_NAMES)
        else None
    )

    keywords: list[dict[str, Any]] = []
    top_keyword = None
    try:
        import jieba
        from stopwords import filter_words, is_meaningful
        word_counter: Counter = Counter()
        for text in texts:
            for word in jieba.cut(text):
                word = word.strip()
                keep, weight = is_meaningful(word)
                if keep:
                    word_counter[word] += weight
        filtered = filter_words(word_counter, total or 1)[:60]
        if filtered:
            max_c = filtered[0][1] or 1
            keywords = [
                {'word': w, 'count': int(c), 'weight': float(c) / float(max_c)}
                for w, c in filtered
            ]
            top_keyword = {'word': filtered[0][0], 'count': int(filtered[0][1])}
    except Exception:
        pass

    members_ranked = [
        {
            'name': name,
            'count': int(cnt),
            'share': round(cnt / total, 4) if total else 0.0,
            'media_count': int(member_media.get(name, 0)),
        }
        for name, cnt in member_counter.most_common(40)
    ]

    # Prefer longer text snippets as "highlights"
    highlights.sort(key=lambda h: (-h['score'], -h['ts']))
    lim = max(0, int(highlight_limit))
    highlights = [
        {k: v for k, v in h.items() if k != 'score'}
        for h in highlights[:lim]
    ]

    speaking = member_speaking_stats(
        decrypted_dir=decrypted_dir,
        chatroom_id=uname,
        speaker_counts=dict(member_counter),
    )

    return {
        'ok': True,
        'chat_id': uname,
        'display_name': display,
        'preset': preset,
        'range_label': label,
        'start_date': start_d.isoformat(),
        'end_date': end_d.isoformat(),
        'start_ts': start_ts,
        'end_ts': end_ts,
        'generated_at': datetime.now(TZ).isoformat(timespec='seconds'),
        'overview': {
            'total_messages': total,
            'active_days': len(active_days),
            'messages_per_day': round(total / max(len(active_days), 1), 2),
            'unique_speakers': len(member_counter),
            'me_messages': me_count,
            'peer_messages': peer_count,
            'media_count': media,
            'sticker_count': stickers,
            'voice_count': voice,
            'system_skipped': system_skipped,
            'peak_hour': peak_hour,
            'peak_weekday': peak_dow_name,
        },
        'members': members_ranked,
        'types': [{'name': n, 'count': int(c)} for n, c in type_counter.most_common(12)],
        'hourly': [int(hourly.get(h, 0)) for h in range(24)],
        'heatmap': {
            'weekday_labels': list(DOW_NAMES),
            'hour_labels': [f'{h:02d}' for h in range(24)],
            'matrix': matrix,
            'total_messages': total,
        },
        'keywords': keywords,
        'top_keyword': top_keyword,
        'highlights': highlights,
        'speaking': speaking,
        'note': (
            '本报告为本地确定性统计（无 AI 总结）。'
            '沉默成员依赖通讯录成员解析；解析不全时含义见 speaking.limitations。'
        ),
    }


def render_group_report_html(report: dict[str, Any]) -> str:
    """Self-contained offline HTML for a group daily report."""
    ov = report.get('overview') or {}
    display = html.escape(str(report.get('display_name') or report.get('chat_id') or ''))
    label = html.escape(str(report.get('range_label') or ''))
    start = html.escape(str(report.get('start_date') or ''))
    end = html.escape(str(report.get('end_date') or ''))
    generated = html.escape(str(report.get('generated_at') or ''))

    def _pills(items: list[tuple[str, Any]]) -> str:
        parts = []
        for title, val in items:
            parts.append(
                f'<div class="pill"><div class="pv">{html.escape(str(val))}</div>'
                f'<div class="pl">{html.escape(title)}</div></div>'
            )
        return '<div class="pills">' + ''.join(parts) + '</div>'

    def _rank(rows: list[dict], name_key='name', count_key='count') -> str:
        if not rows:
            return '<p class="muted">暂无数据</p>'
        max_c = max(int(r.get(count_key) or 0) for r in rows) or 1
        out = ['<div class="rank">']
        for i, r in enumerate(rows, 1):
            name = html.escape(str(r.get(name_key) or ''))
            cnt = int(r.get(count_key) or 0)
            w = round(100.0 * cnt / max_c, 1)
            out.append(
                f'<div class="rr"><span class="ri">{i}</span>'
                f'<span class="rn">{name}</span>'
                f'<span class="rt"><span style="width:{w}%"></span></span>'
                f'<span class="rv">{cnt}</span></div>'
            )
        out.append('</div>')
        return ''.join(out)

    members_html = _rank(report.get('members') or [])
    silent = (report.get('speaking') or {}).get('silent_members') or []
    silent_html = _rank(
        [{'name': s.get('display_name'), 'count': 0} for s in silent[:40]],
    ) if silent else '<p class="muted">窗口内成员均有发言，或成员名单不可用</p>'
    if silent:
        # show names without fake bars
        silent_html = '<ul class="silent">' + ''.join(
            f'<li>{html.escape(str(s.get("display_name") or s.get("wxid") or ""))}</li>'
            for s in silent[:60]
        ) + '</ul>'

    kw = report.get('keywords') or []
    kw_html = '<div class="cloud">' + ''.join(
        f'<span style="font-size:{12 + int((k.get("weight") or 0) * 22)}px">'
        f'{html.escape(str(k.get("word") or ""))}</span>'
        for k in kw[:40]
    ) + '</div>' if kw else '<p class="muted">暂无关键词</p>'

    hl = report.get('highlights') or []
    hl_html = ''.join(
        '<div class="hl"><div class="hm">'
        f'{html.escape(str(h.get("time") or ""))} · {html.escape(str(h.get("sender") or ""))}'
        f'</div><div class="ht">{html.escape(str(h.get("text") or ""))}</div></div>'
        for h in hl
    ) or '<p class="muted">暂无文本摘录</p>'

    limitations = (report.get('speaking') or {}).get('limitations') or []
    lim_html = ''.join(f'<li>{html.escape(str(x))}</li>' for x in limitations)

    types = report.get('types') or []
    types_html = _rank(types, name_key='name', count_key='count')

    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>群聊日报 — {display}</title>
<style>
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Noto Sans SC",sans-serif;
  margin:0;padding:24px;background:#0b1411;color:#e8f7ee;line-height:1.55}}
.wrap{{max-width:880px;margin:0 auto}}
h1{{font-size:22px;margin:0 0 4px}}
.sub{{color:#8fb9a6;font-size:13px;margin:0 0 18px}}
.card{{background:#143028;border:1px solid #2f6b54;padding:16px 18px;margin:0 0 14px}}
.card h2{{font-size:16px;margin:0 0 10px;color:#ff7a45}}
.pills{{display:flex;flex-wrap:wrap;gap:10px}}
.pill{{flex:1;min-width:100px;background:#0a1612;border:1px solid #2f6b54;padding:12px}}
.pv{{font-size:22px;font-weight:700}}.pl{{font-size:11px;color:#8fb9a6;margin-top:2px}}
.rank .rr{{display:flex;align-items:center;gap:8px;margin:0 0 6px;font-size:13px}}
.ri{{width:24px;color:#8fb9a6;text-align:right}}.rn{{width:120px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.rt{{flex:1;height:12px;background:#0a1612;border:1px solid #2f6b54}}
.rt>span{{display:block;height:100%;background:#ff7a45}}.rv{{width:48px;text-align:right}}
.cloud span{{display:inline-block;padding:2px 6px;color:#e04570}}
.hl{{border-bottom:1px solid #2f6b54;padding:8px 0}}.hm{{font-size:12px;color:#8fb9a6}}
.ht{{white-space:pre-wrap;word-break:break-word}}
.silent{{margin:0;padding-left:18px;columns:2;gap:24px}}
.muted{{color:#8fb9a6;font-size:13px}}
.note{{font-size:12px;color:#8fb9a6}}
ul.lim{{font-size:12px;color:#f4a261;margin:8px 0 0;padding-left:18px}}
</style></head><body><div class="wrap">
<h1>{display}</h1>
<p class="sub">群聊日报 · {label}（{start} ~ {end}）· 生成于 {generated}</p>
<div class="card"><h2>概览</h2>
{_pills([
    ('总消息', ov.get('total_messages', 0)),
    ('发言人数', ov.get('unique_speakers', 0)),
    ('活跃天数', ov.get('active_days', 0)),
    ('日均', ov.get('messages_per_day', 0)),
    ('图片/视频', ov.get('media_count', 0)),
    ('语音', ov.get('voice_count', 0)),
    ('最活跃时段', (str(ov.get('peak_hour')) + ':00') if ov.get('peak_hour') is not None else '—'),
    ('最活跃星期', ov.get('peak_weekday') or '—'),
])}
</div>
<div class="card"><h2>发言排行</h2>{members_html}</div>
<div class="card"><h2>沉默成员</h2>{silent_html}
<ul class="lim">{lim_html}</ul></div>
<div class="card"><h2>消息类型</h2>{types_html}</div>
<div class="card"><h2>关键词</h2>{kw_html}</div>
<div class="card"><h2>文本摘录</h2>{hl_html}</div>
<p class="note">{html.escape(str(report.get('note') or ''))}</p>
</div></body></html>
"""


def save_group_report_html(report: dict[str, Any], out_dir: str) -> str:
    """Write HTML to out_dir and return absolute path."""
    os.makedirs(out_dir, exist_ok=True)
    safe = re_safe_name(str(report.get('display_name') or report.get('chat_id') or 'group'))
    fname = f"group_report_{safe}_{report.get('start_date')}_{report.get('end_date')}.html"
    path = os.path.join(out_dir, fname)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(render_group_report_html(report))
    return path


def re_safe_name(name: str, max_len: int = 40) -> str:
    import re as _re
    s = _re.sub(r'[\\/:*?"<>|\s]+', '_', name).strip('_')
    return (s or 'group')[:max_len]
