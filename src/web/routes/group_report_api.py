# -*- coding: utf-8 -*-
"""Group daily report + member speaking/silent stats API."""
from __future__ import annotations

import os
from flask import Blueprint, current_app, jsonify, request, Response

group_report_bp = Blueprint('group_report_api', __name__, url_prefix='/api/group')


def _decrypted_dir() -> str:
    return current_app.config.get('DECRYPTED_DIR') or ''


@group_report_bp.route('/report', methods=['POST', 'GET'])
def group_report():
    """Build a date-range group daily report (JSON).

    Body / query:
      chat (required), preset=today|yesterday|7d|30d|custom,
      start_date, end_date (for custom), highlight_limit
    """
    data = request.get_json(silent=True) if request.method == 'POST' else None
    data = data or {}
    args = request.args

    def _get(key, default=None):
        if key in data and data[key] not in (None, ''):
            return data[key]
        return args.get(key, default)

    chat = (_get('chat') or '').strip()
    if not chat:
        return jsonify({'ok': False, 'error': '缺少 chat'}), 400
    decrypted = _decrypted_dir()
    if not decrypted or not os.path.isdir(decrypted):
        return jsonify({'ok': False, 'error': '尚未完成一键备份，无可用数据目录'}), 400

    preset = (_get('preset') or 'today').strip().lower()
    start_date = (_get('start_date') or '').strip() or None
    end_date = (_get('end_date') or '').strip() or None
    try:
        highlight_limit = int(_get('highlight_limit') or 12)
    except (TypeError, ValueError):
        highlight_limit = 12

    from engine.services.group_report import build_group_report
    try:
        report = build_group_report(
            decrypted, chat,
            preset=preset,
            start_date=start_date,
            end_date=end_date,
            highlight_limit=highlight_limit,
        )
        return jsonify(report)
    except ValueError as e:
        return jsonify({'ok': False, 'error': str(e)}), 400
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@group_report_bp.route('/report/html', methods=['POST', 'GET'])
def group_report_html():
    """Same as /report but returns a downloadable HTML file."""
    data = request.get_json(silent=True) if request.method == 'POST' else None
    data = data or {}
    args = request.args

    def _get(key, default=None):
        if key in data and data[key] not in (None, ''):
            return data[key]
        return args.get(key, default)

    chat = (_get('chat') or '').strip()
    if not chat:
        return jsonify({'ok': False, 'error': '缺少 chat'}), 400
    decrypted = _decrypted_dir()
    if not decrypted or not os.path.isdir(decrypted):
        return jsonify({'ok': False, 'error': '尚未完成一键备份，无可用数据目录'}), 400

    from engine.services.group_report import (
        build_group_report, render_group_report_html, re_safe_name,
    )
    try:
        report = build_group_report(
            decrypted, chat,
            preset=(_get('preset') or 'today').strip().lower(),
            start_date=(_get('start_date') or '').strip() or None,
            end_date=(_get('end_date') or '').strip() or None,
        )
    except ValueError as e:
        return jsonify({'ok': False, 'error': str(e)}), 400
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

    body = render_group_report_html(report)
    fname = 'group_report_%s_%s_%s.html' % (
        re_safe_name(str(report.get('display_name') or 'group')),
        report.get('start_date'),
        report.get('end_date'),
    )
    return Response(
        body,
        mimetype='text/html; charset=utf-8',
        headers={
            'Content-Disposition': f'attachment; filename="{fname}"',
            'Cache-Control': 'no-store',
        },
    )


@group_report_bp.route('/<path:chat_id>/member-stats', methods=['GET'])
def group_member_stats(chat_id: str):
    """GET speaking / silent member stats for a date range.

    Query: preset / start_date / end_date — same semantics as /report.
    """
    decrypted = _decrypted_dir()
    if not decrypted or not os.path.isdir(decrypted):
        return jsonify({'ok': False, 'error': '尚未完成一键备份，无可用数据目录'}), 400
    chat_id = (chat_id or '').strip()
    if not chat_id.endswith('@chatroom'):
        return jsonify({'ok': False, 'error': 'chat_id 必须是群聊 username'}), 400

    from engine.services.group_report import build_group_report
    try:
        report = build_group_report(
            decrypted, chat_id,
            preset=(request.args.get('preset') or '7d').strip().lower(),
            start_date=(request.args.get('start_date') or '').strip() or None,
            end_date=(request.args.get('end_date') or '').strip() or None,
            highlight_limit=0,
        )
    except ValueError as e:
        return jsonify({'ok': False, 'error': str(e)}), 400
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

    speaking = report.get('speaking') or {}
    return jsonify({
        'ok': True,
        'chat_id': report.get('chat_id'),
        'display_name': report.get('display_name'),
        'start_date': report.get('start_date'),
        'end_date': report.get('end_date'),
        'range_label': report.get('range_label'),
        'overview': report.get('overview'),
        **speaking,
    })
