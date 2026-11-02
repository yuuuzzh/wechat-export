# -*- coding: utf-8 -*-
"""Year-over-year comparison API."""
from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request

yoy_bp = Blueprint('yoy_api', __name__, url_prefix='/api/yoy')


def _decrypted() -> str:
    return current_app.config.get('DECRYPTED_DIR') or ''


def _own_wxid() -> str:
    return (current_app.config.get('WXID') or '').strip()


@yoy_bp.route('/compare', methods=['GET', 'POST'])
def yoy_compare():
    """Compare year vs year-1 (optional chat filter)."""
    from engine.services.yoy import build_yoy_report

    data = request.get_json(silent=True) or {}
    args = request.args

    def _get(name, default=None):
        if name in data and data.get(name) not in (None, ''):
            return data.get(name)
        return args.get(name, default)

    year_raw = _get('year')
    try:
        year = int(year_raw) if year_raw not in (None, '') else None
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'error': 'year 必须是整数'}), 400

    try:
        result = build_yoy_report(
            _decrypted(),
            year=year,
            chat=str(_get('chat', '') or '').strip() or None,
            own_wxid=_own_wxid() or None,
        )
    except ValueError as e:
        return jsonify({'ok': False, 'error': str(e)}), 400

    status = 200 if result.get('ok') else 400
    return jsonify(result), status
