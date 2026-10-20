# -*- coding: utf-8 -*-
"""专项导出 API：收藏 + 文件传输助手。"""
from __future__ import annotations

import os
import threading
from datetime import datetime

from flask import Blueprint, current_app, jsonify, request, send_file

from web.sse import create_sse_progress, sse_response

specials_bp = Blueprint('specials_api', __name__, url_prefix='/api/specials')


def _decrypted() -> str:
    return current_app.config.get('DECRYPTED_DIR') or ''


def _out_dir() -> str:
    base = _decrypted() or os.getcwd()
    out = os.path.join(base, 'exports', 'specials')
    os.makedirs(out, exist_ok=True)
    return out


def _ts(raw: str):
    raw = (raw or '').strip()
    if not raw:
        return None
    if raw.isdigit():
        return int(raw)
    for fmt in ('%Y-%m-%d', '%Y-%m-%d %H:%M', '%Y-%m-%d %H:%M:%S'):
        try:
            return int(datetime.strptime(raw, fmt).timestamp())
        except ValueError:
            continue
    return None


@specials_bp.route('/status')
def specials_status():
    from engine.services.specials import favorites_status, filehelper_status
    dec = _decrypted()
    return jsonify({
        'ok': True,
        'favorites': favorites_status(dec),
        'filehelper': filehelper_status(dec),
    })


@specials_bp.route('/favorites')
def specials_favorites():
    from engine.services.specials import list_favorites
    try:
        limit = int(request.args.get('limit') or 50)
    except (TypeError, ValueError):
        limit = 50
    try:
        offset = int(request.args.get('offset') or 0)
    except (TypeError, ValueError):
        offset = 0
    fav_type = request.args.get('type')
    try:
        fav_type = int(fav_type) if fav_type not in (None, '') else None
    except (TypeError, ValueError):
        fav_type = None
    result = list_favorites(
        _decrypted(),
        keyword=request.args.get('q') or '',
        fav_type=fav_type,
        limit=limit,
        offset=offset,
    )
    return jsonify(result), (200 if result.get('ok') else 404)


@specials_bp.route('/favorites/export', methods=['POST'])
def specials_favorites_export():
    data = request.get_json(silent=True) or {}
    fmt = (data.get('format') or 'html').strip().lower()
    if fmt in ('markdown',):
        fmt = 'md'
    if fmt not in ('json', 'html', 'md'):
        return jsonify({'ok': False, 'error': 'format 仅支持 json / html / md'}), 400
    dec = _decrypted()
    out_dir = _out_dir()
    push, gen = create_sse_progress()

    def _run():
        try:
            from engine.services.specials import export_favorites
            push('export', '正在导出收藏…', 0.3)
            stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            ext = 'md' if fmt == 'md' else fmt
            path = os.path.join(out_dir, f'favorites_{stamp}.{ext}')
            fav_type = data.get('type')
            try:
                fav_type = int(fav_type) if fav_type not in (None, '') else None
            except (TypeError, ValueError):
                fav_type = None
            res = export_favorites(
                dec, path, fmt=fmt,
                keyword=data.get('q') or data.get('keyword') or '',
                fav_type=fav_type,
                limit=int(data.get('limit') or 5000),
            )
            if not res.get('ok'):
                push.error(res.get('error') or '导出失败')
                return
            push.done({
                'filename': os.path.basename(path),
                'download_url': '/api/specials/download/' + os.path.basename(path),
                'count': res.get('count') or 0,
            })
        except Exception as e:
            push.error(str(e))

    threading.Thread(target=_run, daemon=True).start()
    return sse_response(gen)


@specials_bp.route('/filehelper/export', methods=['POST'])
def specials_filehelper_export():
    data = request.get_json(silent=True) or {}
    fmt = (data.get('format') or 'html').strip().lower()
    if fmt == 'markdown':
        fmt = 'md'
    if fmt not in ('txt', 'html', 'md', 'json', 'csv'):
        return jsonify({'ok': False, 'error': 'format 仅支持 html / md / json / txt / csv'}), 400
    dec = _decrypted()
    out_dir = _out_dir()
    push, gen = create_sse_progress()

    def _run():
        try:
            from engine.services.specials import export_filehelper
            push('export', '正在导出文件传输助手…', 0.3)
            # export_chat writes into out_dir with a fixed display name
            res = export_filehelper(
                dec, out_dir, fmt=fmt,
                start_ts=_ts(str(data.get('start') or '')),
                end_ts=_ts(str(data.get('end') or '')),
                keyword=data.get('q') or data.get('keyword') or None,
            )
            if not res.get('ok'):
                push.error(res.get('error') or '导出失败')
                return
            path = res.get('path')
            if not path:
                push.done({'filename': None, 'count': 0, 'hint': res.get('hint') or '没有消息'})
                return
            fname = os.path.basename(path)
            push.done({
                'filename': fname,
                'download_url': '/api/specials/download/' + fname,
                'count': res.get('count') or 0,
            })
        except Exception as e:
            push.error(str(e))

    threading.Thread(target=_run, daemon=True).start()
    return sse_response(gen)


@specials_bp.route('/download/<path:filename>')
def specials_download(filename):
    if '..' in filename or '/' in filename or '\\' in filename:
        return jsonify({'error': 'bad filename'}), 400
    path = os.path.join(_out_dir(), filename)
    if not os.path.isfile(path):
        return jsonify({'error': 'not found'}), 404
    return send_file(path, as_attachment=True)
