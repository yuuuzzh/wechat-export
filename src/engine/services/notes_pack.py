# -*- coding: utf-8 -*-
"""Export chats as a notes package: daily markdown + attachments.

Compatible with Obsidian / Logseq / Notion (import Markdown):

  wechat-notes/
    README.md
    daily/YYYY-MM-DD.md
    attachments/YYYY-MM-DD/<files>
    chats/<safe_name>.md   # per-chat index linking to days
"""
from __future__ import annotations

import os
import re
import shutil
import zipfile
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any, Callable, Optional

from engine.constants import TZ

_MD5_RE = re.compile(
    r'''(?:md5\s*=\s*["']|<md5>|<cdnthumbmd5>)([a-fA-F0-9]{32})''',
    re.I,
)
_SAFE_RE = re.compile(r'[\\/:*?"<>|\s]+')

# Message types that may carry file attachments
_MEDIA_TYPES = {3, 6, 34, 43, 47, 49}


def _safe_name(name: str, fallback: str = 'chat') -> str:
    s = _SAFE_RE.sub('_', str(name or '').strip()).strip('_.')
    return (s[:60] or fallback)


def _extract_md5s(raw: str) -> list[str]:
    if not raw:
        return []
    seen = set()
    out = []
    for m in _MD5_RE.finditer(raw):
        h = m.group(1).lower()
        if h not in seen:
            seen.add(h)
            out.append(h)
    return out


def _ext_for(media_type: int, src_path: str = '') -> str:
    base = os.path.splitext(src_path or '')[1].lower()
    if base and len(base) <= 8:
        return base
    return {
        3: '.jpg', 47: '.jpg',
        43: '.mp4',
        34: '.silk',
        6: '.bin', 49: '.bin',
    }.get(int(media_type or 0), '.bin')


def _resolve_attachment(
    decrypted_dir: str,
    msg: dict[str, Any],
) -> Optional[str]:
    """Best-effort absolute path to a local media file for this message."""
    mtype = int(msg.get('type') or 0)
    if mtype not in _MEDIA_TYPES:
        return None

    # Voice: dedicated locator
    if mtype == 34:
        try:
            from engine.services.media import locate_voice_file
            p = locate_voice_file(
                decrypted_dir,
                '',
                create_time=msg.get('create_time'),
                local_id=msg.get('local_id'),
                chat=msg.get('chat_id'),
            )
            if p and os.path.isfile(p):
                return p
        except Exception:
            pass

    md5s = _extract_md5s(msg.get('raw') or '')
    if not md5s:
        return None

    try:
        from engine.services.media import _resolve_hardlink_path, _try_backup_media_by_md5
    except Exception:
        _resolve_hardlink_path = None
        _try_backup_media_by_md5 = None

    for md5 in md5s[:3]:
        if _try_backup_media_by_md5:
            try:
                p = _try_backup_media_by_md5(decrypted_dir, mtype, md5)
                if p and os.path.isfile(p):
                    return p
            except Exception:
                pass
        if _resolve_hardlink_path:
            try:
                p = _resolve_hardlink_path(
                    decrypted_dir,
                    {'md5': md5, 'media_type': mtype},
                )
                if p and os.path.isfile(p):
                    return p
            except Exception:
                pass
    return None


def _copy_attachment(
    src: str,
    attach_dir: str,
    msg: dict[str, Any],
    used_names: set[str],
) -> Optional[str]:
    """Copy src into attach_dir; return relative filename or None."""
    if not src or not os.path.isfile(src):
        return None
    os.makedirs(attach_dir, exist_ok=True)
    mtype = int(msg.get('type') or 0)
    lid = msg.get('local_id') or 0
    chat_slug = _safe_name(msg.get('chat_id') or 'c', 'c')[:16]
    ext = _ext_for(mtype, src)
    base = f'{chat_slug}_{lid}{ext}'
    name = base
    n = 2
    while name in used_names or os.path.exists(os.path.join(attach_dir, name)):
        name = f'{chat_slug}_{lid}_{n}{ext}'
        n += 1
    dest = os.path.join(attach_dir, name)
    try:
        shutil.copy2(src, dest)
    except OSError:
        try:
            shutil.copyfile(src, dest)
        except OSError:
            return None
    used_names.add(name)
    return name


def _line_for_message(msg: dict[str, Any], attach_rel: Optional[str]) -> str:
    t = (msg.get('timestamp') or '')[-8:]  # HH:MM:SS
    sender = (msg.get('sender') or '').replace('|', '/')
    text = (msg.get('text') or '').replace('\r\n', '\n').replace('\r', '\n')
    # Collapse multi-line into indented block for list readability
    if '\n' in text:
        parts = text.split('\n')
        text = parts[0] + ''.join('\n  ' + p for p in parts[1:] if p is not None)

    if attach_rel:
        mtype = int(msg.get('type') or 0)
        link = f'attachments/{msg.get("date")}/{attach_rel}'
        if mtype in (3, 47):
            body = f'![]({link})'
            if text and text not in ('[图片]', '[表情]'):
                body = f'{text}  \n  {body}'
        elif mtype == 43:
            body = f'[视频]({link})'
        elif mtype == 34:
            spoken = text.replace('[语音]', '').strip()
            body = f'[语音]({link})' + (f' {spoken}' if spoken else '')
        else:
            body = f'[附件]({link})' + (f' {text}' if text and not text.startswith('[') else '')
        return f'- **{t}** {sender}：{body}'
    return f'- **{t}** {sender}：{text}'


def _write_daily_note(
    path: str,
    day: str,
    by_chat: dict[str, list[dict[str, Any]]],
    attach_map: dict[tuple, Optional[str]],
) -> int:
    lines = [
        '---',
        f'date: {day}',
        'tags: [wechat, daily]',
        '---',
        '',
        f'# {day}',
        '',
    ]
    count = 0
    for chat_name in sorted(by_chat.keys(), key=lambda x: x.lower()):
        msgs = by_chat[chat_name]
        lines.append(f'## {chat_name}')
        lines.append('')
        for m in msgs:
            key = (m.get('chat_id'), m.get('local_id'), m.get('create_time'))
            lines.append(_line_for_message(m, attach_map.get(key)))
            count += 1
        lines.append('')
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    return count


def _write_chat_index(
    path: str,
    chat_name: str,
    chat_id: str,
    days: list[str],
    msg_count: int,
) -> None:
    lines = [
        '---',
        f'chat_id: "{chat_id}"',
        f'tags: [wechat, chat]',
        '---',
        '',
        f'# {chat_name}',
        '',
        f'- 消息约 **{msg_count}** 条',
        f'- 涉及日期 **{len(days)}** 天',
        '',
        '## 日记链接',
        '',
    ]
    for d in days:
        # Obsidian wikilink + standard relative link
        lines.append(f'- [[{d}]] · [{d}](../daily/{d}.md)')
    lines.append('')
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))


def _write_readme(path: str, stats: dict[str, Any]) -> None:
    text = f"""# WeChat Notes Pack

由 WeChat Export 导出的**按日笔记 + 附件**包，可直接用于 Obsidian / Logseq / Notion。

## 目录

- `daily/` — 按日 Markdown（`YYYY-MM-DD.md`）
- `attachments/YYYY-MM-DD/` — 当日图片 / 视频 / 语音 / 文件（能解析到本地的才会复制）
- `chats/` — 按会话索引（链回日记）

## 导入方式

### Obsidian
1. 将本目录作为 Vault 打开，或复制进现有 Vault
2. 可选：设置 → 日记 → 日记文件夹设为 `daily`

### Logseq
1. 将 `daily/` 中的文件复制到 Graph 的 `journals/`（或把本包当作 graph 根并调整 journals 目录）
2. 附件路径为相对链接，保持 `attachments/` 与日记相对位置不变

### Notion
1. Import → Markdown & CSV → 选择本 ZIP 解压后的文件夹
2. 图片以相对路径嵌入；若个别附件未显示，可手动上传 `attachments/` 中对应文件

## 统计

- 会话数：{stats.get('chat_count', 0)}
- 消息数：{stats.get('msg_count', 0)}
- 日记天数：{stats.get('day_count', 0)}
- 附件数：{stats.get('attach_count', 0)}
- 导出时间：{stats.get('generated_at', '')}

未找到本地文件的图片/语音仍保留文字占位（如 `[图片]`）；可先跑备份与媒体完整性补迁后再导出。
"""
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text)


def build_notes_pack(
    decrypted_dir: str,
    chat_infos: list[dict[str, Any]],
    out_dir: str,
    *,
    start_ts: Optional[int] = None,
    end_ts: Optional[int] = None,
    keyword: Optional[str] = None,
    include_asr: bool = True,
    zip_name: Optional[str] = None,
    print_fn: Optional[Callable[[str], None]] = None,
    progress_fn: Optional[Callable[[float, str], None]] = None,
) -> dict[str, Any]:
    """Build notes package under out_dir and return zip path + stats."""
    from chat_export import collect_messages

    log = print_fn or (lambda m: None)
    progress = progress_fn or (lambda p, m: None)

    if not chat_infos:
        return {'ok': False, 'error': '未选择会话'}

    stamp = datetime.now(tz=TZ).strftime('%Y%m%d_%H%M%S')
    work = os.path.join(out_dir, f'_notes_work_{stamp}')
    daily_dir = os.path.join(work, 'daily')
    attach_root = os.path.join(work, 'attachments')
    chats_dir = os.path.join(work, 'chats')
    os.makedirs(daily_dir, exist_ok=True)
    os.makedirs(attach_root, exist_ok=True)
    os.makedirs(chats_dir, exist_ok=True)

    # day -> chat_name -> [msgs]
    day_map: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    chat_days: dict[str, set[str]] = defaultdict(set)
    chat_counts: Counter = Counter()
    chat_meta: dict[str, dict] = {}
    attach_map: dict[tuple, Optional[str]] = {}
    day_used_names: dict[str, set[str]] = defaultdict(set)
    attach_count = 0
    total_msgs = 0

    n_chats = len(chat_infos)
    for i, info in enumerate(chat_infos):
        display = info.get('display_name') or info.get('username') or 'chat'
        progress(0.05 + 0.7 * i / max(n_chats, 1), f'收集 {display}…')
        log(f'收集会话：{display}')
        try:
            msgs = collect_messages(
                info,
                start_ts=start_ts,
                end_ts=end_ts,
                keyword=keyword,
                include_asr=include_asr,
                include_raw=True,
                display_name=display,
            )
        except Exception as e:
            log(f'跳过 {display}：{e}')
            continue
        cid = info.get('username') or ''
        chat_meta[cid] = {
            'display_name': display,
            'is_group': bool(cid.endswith('@chatroom') or info.get('is_group')),
        }
        for m in msgs:
            day = m.get('date') or ''
            if not day:
                continue
            day_map[day][display].append(m)
            chat_days[cid].add(day)
            chat_counts[cid] += 1
            total_msgs += 1

            mtype = int(m.get('type') or 0)
            if mtype not in _MEDIA_TYPES:
                continue
            key = (m.get('chat_id'), m.get('local_id'), m.get('create_time'))
            if key in attach_map:
                continue
            src = _resolve_attachment(decrypted_dir, m)
            if not src:
                attach_map[key] = None
                continue
            day_attach = os.path.join(attach_root, day)
            fname = _copy_attachment(src, day_attach, m, day_used_names[day])
            attach_map[key] = fname
            if fname:
                attach_count += 1

    if total_msgs == 0:
        shutil.rmtree(work, ignore_errors=True)
        return {'ok': False, 'error': '没有可导出的消息（检查日期/关键词）'}

    progress(0.8, '写日记…')
    for day in sorted(day_map.keys()):
        _write_daily_note(
            os.path.join(daily_dir, f'{day}.md'),
            day,
            day_map[day],
            attach_map,
        )

    progress(0.88, '写会话索引…')
    for cid, meta in chat_meta.items():
        days = sorted(chat_days.get(cid) or [])
        if not days:
            continue
        fname = _safe_name(meta['display_name'], _safe_name(cid))
        _write_chat_index(
            os.path.join(chats_dir, f'{fname}.md'),
            meta['display_name'],
            cid,
            days,
            int(chat_counts.get(cid) or 0),
        )

    stats = {
        'chat_count': len([c for c in chat_counts if chat_counts[c]]),
        'msg_count': total_msgs,
        'day_count': len(day_map),
        'attach_count': attach_count,
        'generated_at': datetime.now(tz=TZ).strftime('%Y-%m-%d %H:%M:%S'),
    }
    _write_readme(os.path.join(work, 'README.md'), stats)

    progress(0.94, '打包 ZIP…')
    os.makedirs(out_dir, exist_ok=True)
    zname = zip_name or f'wechat_notes_{stamp}.zip'
    zpath = os.path.join(out_dir, zname)
    with zipfile.ZipFile(zpath, 'w', zipfile.ZIP_DEFLATED) as zf:
        for root, _dirs, files in os.walk(work):
            for fn in files:
                abs_p = os.path.join(root, fn)
                rel = os.path.relpath(abs_p, work).replace('\\', '/')
                zf.write(abs_p, arcname=f'wechat-notes/{rel}')

    shutil.rmtree(work, ignore_errors=True)
    progress(1.0, '完成')
    log(f'笔记包已生成：{zname}（{total_msgs} 条消息，{attach_count} 个附件）')
    return {
        'ok': True,
        'zip_path': zpath,
        'filename': zname,
        'stats': stats,
    }
