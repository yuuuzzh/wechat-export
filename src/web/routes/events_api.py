# -*- coding: utf-8 -*-
"""Topic / event timeline API."""
from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request

events_bp = Blueprint('events_api', __name__, url_prefix='/api/events')


def _decrypted() -> str:
    return current_app.config.get('DECRYPTED_DIR') or ''


@events_bp.route('/timeline', methods=['POST', 'GET'])
def events_timeline():
    """Build event cards from keywords.

    Body / query:
      keywords | q: str (comma / newline separated)
      gap_hours: float (default 72)
      date_start, date_end: YYYY-MM-DD
      chat: optional session filter
      max_per_keyword: int
      merge_related: bool (default true)
    """
    from engine.services.events import build_event_timeline, parse_keywords

    data = request.get_json(silent=True) or {}
    args = request.args

    raw = (
        data.get('keywords')
        or data.get('q')
        or args.get('keywords')
        or args.get('q')
        or ''
    )
    if isinstance(raw, list):
        keywords = parse_keywords(','.join(str(x) for x in raw))
    else:
        keywords = parse_keywords(str(raw))

    def _num(name, default):
        v = data.get(name) if name in data else args.get(name)
        if v is None or v == '':
            return default
        try:
            return float(v) if name == 'gap_hours' else int(v)
        except (TypeError, ValueError):
            return default

    merge = data.get('merge_related')
    if merge is None:
        merge = args.get('merge_related')
    if merge in (None, ''):
        merge_related = True
    else:
        merge_related = merge not in (False, 0, '0', 'false', 'False', 'off')

    result = build_event_timeline(
        _decrypted(),
        keywords,
        gap_hours=_num('gap_hours', 72),
        date_start=(data.get('date_start') or args.get('date_start') or '').strip() or None,
        date_end=(data.get('date_end') or args.get('date_end') or '').strip() or None,
        chat=(data.get('chat') or args.get('chat') or '').strip() or None,
        max_per_keyword=int(_num('max_per_keyword', 3000)),
        merge_related=merge_related,
    )
    status = 200 if result.get('ok') else 400
    return jsonify(result), status
