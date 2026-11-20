# -*- coding: utf-8 -*-
"""Multi-account workspace: list / switch backup roots without restart."""
from __future__ import annotations

import os
from collections import defaultdict

from flask import Blueprint, current_app, jsonify, request

workspace_bp = Blueprint('workspace', __name__, url_prefix='/api/workspace')


def _safe_path(p: str) -> str:
    return os.path.abspath(os.path.expanduser((p or '').strip()))


@workspace_bp.route('', methods=['GET'])
@workspace_bp.route('/status', methods=['GET'])
def workspace_status():
    """GET /api/workspace — current working set + accounts grouped by wxid."""
    from backup.versions import is_backup_dir, list_versions, load_version_meta
    from engine.config_file import get_backup_data_dir, get_backup_wxid, get_db_dir
    from engine.services.media import resolve_account_dir

    current = get_backup_data_dir() or current_app.config.get('DECRYPTED_DIR') or ''
    current_abs = os.path.abspath(current) if current else ''
    wxid = (current_app.config.get('WXID') or get_backup_wxid() or '').strip()
    versions = list_versions(limit=100)

    by_account: dict[str, list] = defaultdict(list)
    for v in versions:
        key = (v.get('wxid') or 'unknown').strip() or 'unknown'
        path = os.path.abspath(v.get('path') or '')
        entry = {
            'id': v.get('id'),
            'path': path,
            'wxid': key,
            'created_at': v.get('created_at'),
            'chat_count': v.get('chat_count'),
            'message_count': v.get('message_count'),
            'active': bool(current_abs and path == current_abs),
        }
        by_account[key].append(entry)

    accounts = []
    for aid, items in sorted(by_account.items(), key=lambda x: x[0]):
        items.sort(key=lambda x: int(x.get('created_at') or 0), reverse=True)
        accounts.append({
            'wxid': aid,
            'label': aid if aid != 'unknown' else '未标记账号',
            'versions': items,
            'latest': items[0] if items else None,
            'active': any(i.get('active') for i in items),
        })

    has_message = bool(
        current_abs and (
            os.path.isdir(os.path.join(current_abs, 'message'))
            or any(
                n.startswith('message_') and n.endswith('.db')
                for n in (os.listdir(current_abs) if os.path.isdir(current_abs) else [])
            )
        )
    )
    db_dir = get_db_dir() or ''
    return jsonify({
        'ok': True,
        'current': current_abs or None,
        'wxid': wxid or None,
        'db_dir': db_dir or None,
        'accounts': accounts,
        'ready': {
            'has_db_dir': bool(db_dir and os.path.isdir(db_dir)),
            'has_backup': bool(current_abs and is_backup_dir(current_abs)),
            'has_messages': has_message,
            'has_wxid': bool(wxid),
        },
        'current_meta': load_version_meta(current_abs) if current_abs and is_backup_dir(current_abs) else None,
        'resolved_wxid': resolve_account_dir(current_abs, wxid) if current_abs else wxid,
    })


@workspace_bp.route('/switch', methods=['POST'])
def workspace_switch():
    """POST /api/workspace/switch — activate a backup dir as working set."""
    from backup.versions import activate_version
    from engine.services.media import resolve_account_dir

    data = request.get_json(silent=True) or {}
    path = data.get('path') or data.get('backup_dir') or ''
    if not path:
        return jsonify({'ok': False, 'error': '缺少 path'}), 400
    path = _safe_path(path)
    wxid = (data.get('wxid') or '').strip()
    result = activate_version(path, wxid=wxid)
    if not result.get('ok'):
        return jsonify(result), 400

    current_app.config['DECRYPTED_DIR'] = result['path']
    use_wxid = result.get('wxid') or wxid or ''
    try:
        current_app.config['WXID'] = resolve_account_dir(result['path'], use_wxid)
    except Exception:
        current_app.config['WXID'] = use_wxid
    result['decrypted_dir'] = result['path']
    result['wxid'] = current_app.config.get('WXID')
    return jsonify(result)
