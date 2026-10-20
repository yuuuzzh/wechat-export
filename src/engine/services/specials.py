# -*- coding: utf-8 -*-
"""专项导出：收藏（favorite.db）与文件传输助手（filehelper）。

收藏库只在密钥覆盖时存在于备份中；文件传输助手是普通会话
``filehelper``，消息在 ``message_*.db`` 的 ``Msg_<md5>`` 表里。
"""
from __future__ import annotations

import hashlib
import html
import json
import os
import re
import sqlite3
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Any, Optional

FILEHELPER_ID = 'filehelper'
FILEHELPER_NAME = '文件传输助手'

# WeChat 4.x fav type numbers (plus common 3.x aliases — labels stay readable)
FAV_TYPE_LABELS = {
    1: '文本',
    2: '图片',
    3: '语音',
    4: '视频',
    5: '链接',
    6: '位置',
    7: '附件',
    8: '文件',
    14: '聊天记录',
    15: '笔记',
    16: '小程序',
    43: '视频号',
    49: '链接',
}

try:
    import zstandard as zstd
    _ZSTD = zstd.ZstdDecompressor()
except ImportError:
    zstd = None
    _ZSTD = None


def find_favorite_db(decrypted_dir: str) -> Optional[str]:
    if not decrypted_dir:
        return None
    candidates = [
        os.path.join(decrypted_dir, 'favorite', 'favorite.db'),
        os.path.join(decrypted_dir, 'favorite.db'),
    ]
    if os.path.isdir(decrypted_dir):
        try:
            for name in os.listdir(decrypted_dir):
                candidates.append(os.path.join(decrypted_dir, name, 'favorite', 'favorite.db'))
        except OSError:
            pass
    for p in candidates:
        if p and os.path.isfile(p):
            return p
    return None


def _tables(conn: sqlite3.Connection) -> list[str]:
    return [
        r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
    ]


def _pick_col(cols: list[str], *names: str) -> Optional[str]:
    lower = {c.lower(): c for c in cols}
    for n in names:
        hit = lower.get(n.lower())
        if hit:
            return hit
    return None


def _as_text(value) -> str:
    if value is None:
        return ''
    if isinstance(value, str):
        return value
    if isinstance(value, (bytes, bytearray)):
        raw = bytes(value)
        if _ZSTD is not None and raw[:4] == b'\x28\xb5\x2f\xfd':
            try:
                raw = _ZSTD.decompress(raw)
            except Exception:
                pass
        lt = raw.find(b'<')
        if 0 < lt < 64:
            raw = raw[lt:]
        return raw.decode('utf-8', errors='replace')
    return str(value)


def _txt(root, *tags: str) -> str:
    for tag in tags:
        el = root.find(f'.//{tag}')
        if el is not None and (el.text or '').strip():
            return (el.text or '').strip()
    return ''


def parse_fav_xml(xml_text: str, fav_type: int) -> dict[str, Any]:
    """Best-effort title / body / url / source from favorite XML."""
    out = {
        'title': '', 'body': '', 'url': '', 'source': '',
        'chat_lines': [],
    }
    if not xml_text or '<' not in xml_text:
        text = (xml_text or '').strip()
        out['body'] = text[:4000]
        return out
    cleaned = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', xml_text)
    try:
        root = ET.fromstring(cleaned)
    except ET.ParseError:
        out['body'] = cleaned[:2000]
        return out

    out['title'] = _txt(root, 'pagetitle', 'title', 'datatitle', 'sourcedesc')
    out['body'] = _txt(root, 'pagedesc', 'desc', 'datadesc', 'content', 'desc2')
    out['url'] = _txt(root, 'link', 'url', 'pageurl', 'stream_weburl')
    out['source'] = _txt(root, 'sourcename', 'fromnickname', 'fromusr', 'appname')

    lines = []
    for item in root.findall('.//dataitem'):
        who = _txt(item, 'datasrcname', 'sourcename', 'fromnickname')
        desc = _txt(item, 'datadesc', 'datatitle', 'desc')
        if desc:
            lines.append((who + ': ' if who else '') + desc)
    if lines:
        out['chat_lines'] = lines[:80]
        if not out['body']:
            out['body'] = '\n'.join(lines[:40])
        if not out['title'] and fav_type == 14:
            out['title'] = '聊天记录'
    if not out['title'] and out['body']:
        out['title'] = out['body'][:40]
    return out


def _row_item(cols: list[str], row: tuple) -> dict[str, Any]:
    data = dict(zip(cols, row))

    def get(*names):
        col = _pick_col(cols, *names)
        return data.get(col) if col else None

    local_id = get('localId', 'local_id', 'FavLocalID', 'id')
    fav_type = get('type', 'Type', 'favType') or 0
    try:
        fav_type = int(fav_type)
    except (TypeError, ValueError):
        fav_type = 0
    create_time = get('createTime', 'create_time', 'CreateTime')
    update_time = get('updateTime', 'update_time', 'UpdateTime')
    try:
        create_time = int(create_time) if create_time else None
    except (TypeError, ValueError):
        create_time = None
    try:
        update_time = int(update_time) if update_time else None
    except (TypeError, ValueError):
        update_time = None
    xml_raw = get('xmlBuf', 'xml', 'content', 'Content', 'favXml')
    parsed = parse_fav_xml(_as_text(xml_raw), fav_type)
    tags_raw = get('tagNames', 'tag_names', 'tags') or ''
    tags = [t.strip() for t in re.split(r'[,;，；\s]+', _as_text(tags_raw)) if t.strip()]
    return {
        'id': local_id,
        'type': fav_type,
        'type_label': FAV_TYPE_LABELS.get(fav_type, f'类型{fav_type}'),
        'create_time': create_time,
        'update_time': update_time,
        'title': parsed['title'],
        'body': parsed['body'],
        'url': parsed['url'],
        'source': parsed['source'],
        'chat_lines': parsed['chat_lines'],
        'tags': tags,
    }


def favorites_status(decrypted_dir: str) -> dict[str, Any]:
    path = find_favorite_db(decrypted_dir)
    if not path:
        return {
            'ok': True,
            'available': False,
            'path': None,
            'count': 0,
            'hint': '备份中没有 favorite.db。请打开微信「收藏」后重新提取密钥并一键备份（密钥能覆盖时才会解密该库）。',
        }
    try:
        conn = sqlite3.connect(path)
        names = _tables(conn)
        table = 'fav_db_item' if 'fav_db_item' in names else (
            'FavItems' if 'FavItems' in names else None
        )
        count = 0
        if table:
            count = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
        conn.close()
    except sqlite3.Error as e:
        return {
            'ok': False,
            'available': True,
            'path': path,
            'count': 0,
            'error': str(e),
            'hint': 'favorite.db 已存在但无法读取',
        }
    if not table:
        return {
            'ok': True,
            'available': True,
            'path': path,
            'count': 0,
            'tables': names,
            'hint': 'favorite.db 中未识别 fav_db_item / FavItems 表',
        }
    return {
        'ok': True,
        'available': True,
        'path': path,
        'table': table,
        'count': int(count or 0),
        'hint': None,
    }


def list_favorites(
    decrypted_dir: str,
    *,
    keyword: str = '',
    fav_type: Optional[int] = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    path = find_favorite_db(decrypted_dir)
    if not path:
        st = favorites_status(decrypted_dir)
        return {'ok': False, 'error': st.get('hint'), 'items': [], 'total': 0}

    try:
        conn = sqlite3.connect(path)
        names = _tables(conn)
        table = 'fav_db_item' if 'fav_db_item' in names else (
            'FavItems' if 'FavItems' in names else None
        )
        if not table:
            conn.close()
            return {
                'ok': False,
                'error': '未识别收藏表',
                'tables': names,
                'items': [],
                'total': 0,
            }
        cols = [r[1] for r in conn.execute(f'PRAGMA table_info("{table}")').fetchall()]
        col_sql = ', '.join(f'"{c}"' for c in cols)
        rows = conn.execute(f'SELECT {col_sql} FROM "{table}"').fetchall()
        conn.close()
    except sqlite3.Error as e:
        return {'ok': False, 'error': str(e), 'items': [], 'total': 0}

    kw = (keyword or '').strip().lower()
    items = []
    for row in rows:
        item = _row_item(cols, row)
        if fav_type is not None and item['type'] != fav_type:
            continue
        if kw:
            blob = ' '.join([
                item.get('title') or '',
                item.get('body') or '',
                item.get('url') or '',
                item.get('source') or '',
                ' '.join(item.get('tags') or []),
            ]).lower()
            if kw not in blob:
                continue
        items.append(item)

    items.sort(key=lambda x: -(x.get('create_time') or 0))
    total = len(items)
    limit = max(1, min(2000, int(limit or 50)))
    offset = max(0, int(offset or 0))
    return {
        'ok': True,
        'items': items[offset:offset + limit],
        'total': total,
        'path': path,
    }


def export_favorites(
    decrypted_dir: str,
    out_path: str,
    *,
    fmt: str = 'json',
    keyword: str = '',
    fav_type: Optional[int] = None,
    limit: int = 5000,
) -> dict[str, Any]:
    listed = list_favorites(
        decrypted_dir, keyword=keyword, fav_type=fav_type, limit=limit, offset=0,
    )
    if not listed.get('ok'):
        return listed
    items = listed.get('items') or []
    os.makedirs(os.path.dirname(out_path) or '.', exist_ok=True)
    fmt = (fmt or 'json').lower()
    if fmt == 'html':
        _write_fav_html(out_path, items, keyword)
    elif fmt in ('md', 'markdown'):
        _write_fav_md(out_path, items)
    else:
        fmt = 'json'
        with open(out_path, 'w', encoding='utf-8') as f:
            json.dump({
                'exported_at': datetime.now().isoformat(timespec='seconds'),
                'count': len(items),
                'keyword': keyword,
                'items': items,
            }, f, ensure_ascii=False, indent=2)
    return {'ok': True, 'count': len(items), 'path': out_path, 'format': fmt}


def _fmt_ts(ts) -> str:
    if not ts:
        return ''
    try:
        return datetime.fromtimestamp(int(ts)).strftime('%Y-%m-%d %H:%M:%S')
    except (OSError, OverflowError, ValueError):
        return str(ts)


def _write_fav_md(path: str, items: list[dict]) -> None:
    lines = [f'# 微信收藏导出（{len(items)} 条）', '']
    for it in items:
        title = it.get('title') or it.get('type_label') or '未命名'
        lines.append(f"## {title}")
        lines.append('')
        meta = [it.get('type_label') or '', _fmt_ts(it.get('create_time'))]
        if it.get('source'):
            meta.append(it['source'])
        if it.get('tags'):
            meta.append('标签: ' + ', '.join(it['tags']))
        lines.append('- ' + ' · '.join(x for x in meta if x))
        if it.get('url'):
            lines.append(f"- 链接: {it['url']}")
        if it.get('body'):
            lines.append('')
            lines.append(it['body'])
        lines.append('')
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))


def _write_fav_html(path: str, items: list[dict], keyword: str) -> None:
    blocks = []
    for it in items:
        title = html.escape(it.get('title') or it.get('type_label') or '未命名')
        body = html.escape(it.get('body') or '').replace('\n', '<br>')
        url = it.get('url') or ''
        url_html = (
            f'<div class="url"><a href="{html.escape(url)}">{html.escape(url)}</a></div>'
            if url else ''
        )
        meta = html.escape(' · '.join(x for x in [
            it.get('type_label') or '',
            _fmt_ts(it.get('create_time')),
            it.get('source') or '',
            ('#' + ' #'.join(it['tags'])) if it.get('tags') else '',
        ] if x))
        blocks.append(
            f'<article><h2>{title}</h2><p class="meta">{meta}</p>{url_html}'
            f'<div class="body">{body}</div></article>'
        )
    doc = f'''<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>微信收藏导出</title>
<style>
body{{font-family:sans-serif;background:#111;color:#eee;margin:0;padding:24px}}
article{{border:1px solid #333;padding:12px 16px;margin:0 0 12px;background:#1a1a1a}}
h1{{font-size:18px}} h2{{font-size:15px;margin:0 0 6px}}
.meta,.url{{color:#8fb9a6;font-size:12px}} .body{{white-space:pre-wrap;font-size:14px;margin-top:8px}}
a{{color:#7ec8ff}}
</style></head><body>
<h1>微信收藏 · {len(items)} 条</h1>
<p class="meta">关键词：{html.escape(keyword or "（无）")}</p>
{''.join(blocks) or '<p>没有收藏记录</p>'}
</body></html>'''
    with open(path, 'w', encoding='utf-8') as f:
        f.write(doc)


def _filehelper_tables(decrypted_dir: str) -> list[dict]:
    msg_dir = os.path.join(decrypted_dir or '', 'message')
    if not os.path.isdir(msg_dir):
        return []
    tname = 'Msg_' + hashlib.md5(FILEHELPER_ID.encode()).hexdigest()
    found = []
    try:
        names = sorted(os.listdir(msg_dir))
    except OSError:
        return []
    for fname in names:
        if not (fname.startswith('message_') and fname.endswith('.db')):
            continue
        path = os.path.join(msg_dir, fname)
        try:
            conn = sqlite3.connect(path)
            row = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (tname,),
            ).fetchone()
            count = 0
            if row:
                count = conn.execute(f'SELECT COUNT(*) FROM [{tname}]').fetchone()[0]
            conn.close()
        except sqlite3.Error:
            continue
        if row:
            found.append({
                'db_path': path,
                'table_name': tname,
                'msg_count': int(count or 0),
            })
    return found


def filehelper_status(decrypted_dir: str) -> dict[str, Any]:
    tables = _filehelper_tables(decrypted_dir)
    total = sum(t['msg_count'] for t in tables)
    if not tables:
        return {
            'ok': True,
            'available': False,
            'chat_id': FILEHELPER_ID,
            'display_name': FILEHELPER_NAME,
            'msg_count': 0,
            'hint': '当前备份里没有文件传输助手会话。完成消息库解密后即可导出。',
        }
    return {
        'ok': True,
        'available': True,
        'chat_id': FILEHELPER_ID,
        'display_name': FILEHELPER_NAME,
        'msg_count': total,
        'shards': len(tables),
        'hint': None,
    }


def export_filehelper(
    decrypted_dir: str,
    out_dir: str,
    *,
    fmt: str = 'html',
    start_ts: Optional[int] = None,
    end_ts: Optional[int] = None,
    keyword: Optional[str] = None,
) -> dict[str, Any]:
    tables = _filehelper_tables(decrypted_dir)
    if not tables:
        st = filehelper_status(decrypted_dir)
        return {'ok': False, 'error': st.get('hint'), 'count': 0}
    from chat_export import export_chat
    chat_info = {
        'username': FILEHELPER_ID,
        'display_name': FILEHELPER_NAME,
        'tables': tables,
    }
    os.makedirs(out_dir, exist_ok=True)
    count, path = export_chat(
        chat_info, out_dir,
        start_ts=start_ts, end_ts=end_ts, keyword=keyword,
        fmt=fmt, display_name=FILEHELPER_NAME,
        print_fn=lambda *_a, **_k: None,
    )
    if not path:
        return {'ok': True, 'count': 0, 'path': None, 'hint': '筛选后没有消息'}
    return {'ok': True, 'count': count, 'path': path, 'format': fmt}
