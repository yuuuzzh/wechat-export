# -*- coding: utf-8 -*-
"""First-run setup status for the onboarding wizard."""
from __future__ import annotations

import os

from flask import Blueprint, current_app, jsonify

setup_bp = Blueprint('setup', __name__, url_prefix='/api/setup')


@setup_bp.route('/status', methods=['GET'])
def setup_status():
    """GET /api/setup/status — readiness for first-time wizard."""
    from backup.versions import is_backup_dir
    from engine.config_file import (
        get_backup_data_dir, get_backup_wxid, get_db_dir, _config_path,
    )
    from engine.utils import find_all_wechat_data_dirs, is_wechat_running

    db_dir = get_db_dir() or ''
    accounts = []
    try:
        accounts = find_all_wechat_data_dirs() or []
    except Exception:
        accounts = []

    # Keys present?
    has_keys = False
    try:
        import json
        cfg_path = _config_path()
        if os.path.isfile(cfg_path):
            with open(cfg_path, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
            has_keys = bool(
                cfg.get('db_keys_by_salt')
                or cfg.get('db_keys')
                or cfg.get('image_aes_key')
            )
    except Exception:
        has_keys = False

    current = get_backup_data_dir() or current_app.config.get('DECRYPTED_DIR') or ''
    current_abs = os.path.abspath(current) if current else ''
    has_backup = bool(current_abs and is_backup_dir(current_abs))

    from engine.platform_info import (
        auto_key_extract_supported, is_macos, mac_key_capabilities,
    )

    mac_caps = mac_key_capabilities(db_dir) if is_macos() else {}
    mac_advanced = bool(is_macos() and mac_caps.get('auto_extract_ready'))
    mac_keys = is_macos() or not auto_key_extract_supported()
    keys_title = '提取数据库密钥' if (not mac_keys or mac_advanced) else '准备数据库密钥'
    if mac_advanced:
        keys_hint = (
            'Mac 高级模式已就绪：需临时关闭 SIP + 管理员授权 + 微信停在登录页；'
            '也可手动粘贴密钥或打开已解密备份'
        )
    elif mac_keys:
        keys_hint = 'Mac 默认无自动提钥：看「Mac 密钥指引」后手动粘贴，或打开已解密备份'
    else:
        keys_hint = '微信保持登录；优先内存/配置提取'

    steps = [
        {
            'id': 'detect',
            'title': '检测微信数据目录',
            'done': bool(db_dir and os.path.isdir(db_dir)) or bool(accounts),
            'hint': '需本机已安装并登录过微信',
        },
        {
            'id': 'keys',
            'title': keys_title,
            'done': has_keys,
            'hint': keys_hint,
        },
        {
            'id': 'backup',
            'title': '一键备份解密',
            'done': has_backup,
            'hint': '生成可浏览的本地备份目录',
        },
        {
            'id': 'viewer',
            'title': '打开查看器',
            'done': has_backup,
            'hint': '备份完成后进入聊天浏览 / 导出',
        },
    ]
    next_step = next((s['id'] for s in steps if not s['done']), 'viewer')
    complete = all(s['done'] for s in steps[:3])

    return jsonify({
        'ok': True,
        'complete': complete,
        'next_step': next_step,
        'steps': steps,
        'mac_keys_guide': bool(mac_keys),
        'mac_keys_advanced': mac_advanced,
        'mac_auto_key': mac_caps,
        'wechat_running': bool(is_wechat_running()),
        'accounts': [
            {'wxid': a.get('wxid'), 'db_path': a.get('db_path')}
            for a in accounts[:20]
        ],
        'db_dir': db_dir or None,
        'backup_dir': current_abs or None,
        'wxid': get_backup_wxid(),
    })
