# -*- coding: utf-8 -*-
"""Export chats as a notes package: daily markdown + attachments.

Compatible with Obsidian / Logseq / Notion (import Markdown):

  wechat-notes/
    README.md
    manifest.json
    daily/YYYY-MM-DD.md
    attachments/YYYY-MM-DD/<files>
    chats/<safe_name>.md   # per-chat index linking to days
"""
from __future__ import annotations

import json
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
_IMAGE_TYPES = {3, 47}

_MIME_EXT = {
    'image/jpeg': '.jpg',
    'image/png': '.png',
    'image/gif': '.gif',
    'image/webp': '.webp',
    'image/bmp': '.bmp',
}


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
    if base and len(base) <= 8 and base != '.dat':
        return base
    return {
        3: '.jpg', 47: '.jpg',
        43: '.mp4',
        34: '.silk',
        6: '.bin', 49: '.bin',
    }.get(int(media_type or 0), '.bin')


def _unique_name(attach_dir: str, base: str, used_names: set[str]) -> str:
    name = base
    stem, ext = os.path.splitext(base)
    n = 2
    while name in used_names or os.path.exists(os.path.join(attach_dir, name)):
        name = f'{stem}_{n}{ext}'
        n += 1
    return name


def _cache_dir(decrypted_dir: str) -> str:
    parent = os.path.dirname(os.path.abspath(decrypted_dir or '.')) or '.'
    path = os.path.join(parent, 'decrypted_media')
    os.makedirs(path, exist_ok=True)
    return path


def _decrypt_dat_to_preview(
    decrypted_dir: str,
    src_path: str,
    *,
    md5: Optional[str] = None,
) -> Optional[str]:
    """Decrypt WeChat .dat image → path to sniffed image bytes (*.dec cache).

    Returns None when version/key unknown or output is not a recognizable image.
    """
    if not src_path or not os.path.isfile(src_path):
        return None
    if not src_path.lower().endswith('.dat'):
        return src_path

    try:
        from engine.services.media import (
            _detect_dat_xor_key,
            _detect_wechat_dat_version,
            _decrypt_dat_file,
            _decrypt_dat_v1,
            _decrypt_dat_v2,
            _load_or_build_image_key_map,
            _sniff_image_mime,
        )
    except Exception:
        return None

    cache = _cache_dir(decrypted_dir)
    try:
        with open(src_path, 'rb') as f:
            header = f.read(256)
    except OSError:
        return None

    version = _detect_wechat_dat_version(header)
    dec_path = None

    try:
        if version == 0:
            key, _ext = _detect_dat_xor_key(src_path)
            if key is not None:
                dec_path = _decrypt_dat_file(src_path, key, cache)
        elif version == 1:
            dec_path = _decrypt_dat_v1(src_path, cache)
        else:
            # V2: refresh MMKV-derived keys when possible, then use cache map
            try:
                from engine.services.v2_key_extract import extract_keys_from_mmkv
                extract_keys_from_mmkv(decrypted_dir)
            except Exception:
                pass
            km = {}
            try:
                km = _load_or_build_image_key_map(decrypted_dir) or {}
            except Exception:
                km = {}
            entry = None
            if md5 and md5 in km:
                entry = km[md5]
            elif md5:
                # thumbnail variants sometimes keyed as md5_h / md5_t
                for suffix in ('_h', '_t'):
                    if md5 + suffix in km:
                        entry = km[md5 + suffix]
                        break
            if entry is None and km:
                # account-level fallback: any known key (same account AES)
                entry = next(iter(km.values()))
            if entry and entry.get('aes'):
                xor = entry.get('xor')
                dec_path = _decrypt_dat_v2(
                    src_path, entry['aes'], xor, cache)
    except Exception:
        return None

    if not dec_path or not os.path.isfile(dec_path):
        return None
    try:
        with open(dec_path, 'rb') as f:
            head = f.read(16)
    except OSError:
        return None
    mime = _sniff_image_mime(head)
    if mime == 'application/octet-stream' or mime not in _MIME_EXT:
        return None
    return dec_path


def _resolve_attachment(
    decrypted_dir: str,
    msg: dict[str, Any],
) -> tuple[Optional[str], Optional[str]]:
    """Best-effort (abs_path, md5) for a local media file."""
    mtype = int(msg.get('type') or 0)
    if mtype not in _MEDIA_TYPES:
        return None, None

    md5s = _extract_md5s(msg.get('raw') or '')
    primary_md5 = md5s[0] if md5s else None

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
                return p, primary_md5
        except Exception:
            pass

    if not md5s:
        return None, None

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
                    return p, md5
            except Exception:
                pass
        if _resolve_hardlink_path:
            try:
                p = _resolve_hardlink_path(
                    decrypted_dir,
                    {'md5': md5, 'media_type': mtype},
                )
                if p and os.path.isfile(p):
                    return p, md5
            except Exception:
                pass
    return None, primary_md5


def _materialize_attachment(
    decrypted_dir: str,
    src: str,
    attach_dir: str,
    msg: dict[str, Any],
    used_names: set[str],
    md5: Optional[str] = None,
) -> tuple[Optional[str], Optional[str]]:
    """Copy/decrypt src into attach_dir.

    Returns (relative_filename, error_reason). error_reason set when failed.
    """
    if not src or not os.path.isfile(src):
        return None, 'file_missing'
    os.makedirs(attach_dir, exist_ok=True)
    mtype = int(msg.get('type') or 0)
    lid = msg.get('local_id') or 0
    chat_slug = _safe_name(msg.get('chat_id') or 'c', 'c')[:16]

    copy_src = src
    ext = _ext_for(mtype, src)

    # Images still stored as encrypted .dat → decrypt to previewable format
    if mtype in _IMAGE_TYPES and src.lower().endswith('.dat'):
        preview = _decrypt_dat_to_preview(decrypted_dir, src, md5=md5)
        if not preview:
            return None, 'decrypt_failed'
        copy_src = preview
        try:
            from engine.services.media import _sniff_image_mime
            with open(preview, 'rb') as f:
                mime = _sniff_image_mime(f.read(16))
            ext = _MIME_EXT.get(mime, '.jpg')
        except Exception:
            ext = '.jpg'

    base = f'{chat_slug}_{lid}{ext}'
    name = _unique_name(attach_dir, base, used_names)
    dest = os.path.join(attach_dir, name)
    try:
        shutil.copy2(copy_src, dest)
    except OSError:
        try:
            shutil.copyfile(copy_src, dest)
        except OSError:
            return None, 'copy_failed'
    used_names.add(name)
    return name, None


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


def _write_manifest(
    path: str,
    stats: dict[str, Any],
    missing: list[dict[str, Any]],
    filters: dict[str, Any],
) -> None:
    payload = {
        'format': 'wechat-notes-pack',
        'version': 2,
        'generated_at': stats.get('generated_at'),
        'stats': {
            'chat_count': stats.get('chat_count', 0),
            'msg_count': stats.get('msg_count', 0),
            'day_count': stats.get('day_count', 0),
            'attach_count': stats.get('attach_count', 0),
            'missing_count': len(missing),
        },
        'filters': filters,
        'missing': missing,
    }
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def _write_missing_csv(path: str, missing: list[dict[str, Any]]) -> None:
    lines = ['date,chat_id,local_id,type,md5,reason,text']
    for row in missing:
        def _esc(v: Any) -> str:
            s = str(v if v is not None else '')
            if any(c in s for c in ',"\n'):
                return '"' + s.replace('"', '""') + '"'
            return s
        lines.append(','.join([
            _esc(row.get('date')),
            _esc(row.get('chat_id')),
            _esc(row.get('local_id')),
            _esc(row.get('type')),
            _esc(row.get('md5')),
            _esc(row.get('reason')),
            _esc(row.get('text')),
        ]))
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')


def _write_readme(path: str, stats: dict[str, Any]) -> None:
    missing_n = int(stats.get('missing_count') or 0)
    text = f"""# WeChat Notes Pack

由 WeChat Export 导出的**按日笔记 + 附件**包，可直接用于 Obsidian / Logseq / Notion。

## 目录

- `daily/` — 按日 Markdown（`YYYY-MM-DD.md`）
- `attachments/YYYY-MM-DD/` — 当日图片 / 视频 / 语音 / 文件（图片 `.dat` 会尽量解密为 jpg/png）
- `chats/` — 按会话索引（链回日记）
- `manifest.json` — 统计与缺失附件清单
- `missing.csv` — 同上（表格，便于筛选）

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
- 缺失附件：{missing_n}
- 导出时间：{stats.get('generated_at', '')}

未找到或未能解密的图片/语音仍保留文字占位（如 `[图片]`）；可先跑备份与媒体完整性补迁、确认 `_media_keys.json` / 微信曾登录后再导出。
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
    missing: list[dict[str, Any]] = []
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
            src, md5 = _resolve_attachment(decrypted_dir, m)
            if not src:
                attach_map[key] = None
                missing.append({
                    'date': day,
                    'chat_id': m.get('chat_id'),
                    'chat_name': display,
                    'local_id': m.get('local_id'),
                    'type': mtype,
                    'md5': md5 or '',
                    'reason': 'not_found',
                    'text': (m.get('text') or '')[:80],
                })
                continue
            day_attach = os.path.join(attach_root, day)
            fname, err = _materialize_attachment(
                decrypted_dir, src, day_attach, m, day_used_names[day], md5=md5,
            )
            attach_map[key] = fname
            if fname:
                attach_count += 1
            else:
                missing.append({
                    'date': day,
                    'chat_id': m.get('chat_id'),
                    'chat_name': display,
                    'local_id': m.get('local_id'),
                    'type': mtype,
                    'md5': md5 or '',
                    'reason': err or 'materialize_failed',
                    'text': (m.get('text') or '')[:80],
                })

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
        'missing_count': len(missing),
        'generated_at': datetime.now(tz=TZ).strftime('%Y-%m-%d %H:%M:%S'),
    }
    filters = {
        'start_ts': start_ts,
        'end_ts': end_ts,
        'keyword': keyword or '',
        'include_asr': bool(include_asr),
        'chats': [
            {'username': cid, 'display_name': meta['display_name']}
            for cid, meta in chat_meta.items()
        ],
    }
    _write_readme(os.path.join(work, 'README.md'), stats)
    _write_manifest(os.path.join(work, 'manifest.json'), stats, missing, filters)
    if missing:
        _write_missing_csv(os.path.join(work, 'missing.csv'), missing)

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
    log(
        f'笔记包已生成：{zname}（{total_msgs} 条消息，'
        f'{attach_count} 个附件，缺失 {len(missing)}）'
    )
    return {
        'ok': True,
        'zip_path': zpath,
        'filename': zname,
        'stats': stats,
        'missing': missing,
    }


def export_notes_for_dir(
    decrypted_dir: str,
    out_dir: str,
    *,
    name_filter: Optional[str] = None,
    keyword: Optional[str] = None,
    include_asr: bool = False,
    print_fn: Optional[Callable[[str], None]] = None,
    progress_fn: Optional[Callable[[float, str], None]] = None,
) -> dict[str, Any]:
    """CLI helper: scan chats (optional name filter) then build notes pack."""
    from chat_list import scan_chats

    log = print_fn or print
    chats, _, _ = scan_chats(decrypted_dir)
    selected = []
    for c in chats:
        if name_filter:
            kw = name_filter.lower()
            if kw not in (c.get('display_name') or '').lower() and \
               kw not in (c.get('username') or '').lower():
                continue
        selected.append(c)
    if not selected:
        return {'ok': False, 'error': '没有匹配的会话'}
    log(f'将导出 {len(selected)} 个会话为笔记包…')
    return build_notes_pack(
        decrypted_dir,
        selected,
        out_dir,
        keyword=keyword,
        include_asr=include_asr,
        print_fn=print_fn,
        progress_fn=progress_fn,
    )
