# -*- coding: utf-8 -*-
"""Relationship graph API — friend/group interaction intensity (read-only)."""
from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request

graph_bp = Blueprint('graph_api', __name__, url_prefix='/api/graph')


def _decrypted() -> str:
    return current_app.config.get('DECRYPTED_DIR') or ''


def _own_wxid() -> str:
    return (current_app.config.get('WXID') or '').strip()


@graph_bp.route('/relation', methods=['GET', 'POST'])
def graph_relation():
    """Build ego-centric interaction graph.

    Params (JSON body or query):
      kind: all | friends | groups
      top_n: int (default 40)
      min_messages: int (default 3)
      date_start, date_end: YYYY-MM-DD (needs search index)
      include_members: bool — attach top senders of top groups
      member_top: int
    """
    from engine.services.graph import build_relation_graph

    data = request.get_json(silent=True) or {}
    args = request.args

    def _get(name, default=None):
        if name in data and data.get(name) is not None and data.get(name) != '':
            return data.get(name)
        return args.get(name, default)

    def _bool(name, default=False):
        v = _get(name, None)
        if v is None or v == '':
            return default
        return v not in (False, 0, '0', 'false', 'False', 'off')

    def _int(name, default):
        v = _get(name, default)
        try:
            return int(v)
        except (TypeError, ValueError):
            return default

    result = build_relation_graph(
        _decrypted(),
        kind=str(_get('kind', 'all') or 'all'),
        top_n=_int('top_n', 40),
        min_messages=_int('min_messages', 3),
        date_start=str(_get('date_start', '') or '').strip() or None,
        date_end=str(_get('date_end', '') or '').strip() or None,
        include_members=_bool('include_members', False),
        member_top=_int('member_top', 5),
        own_wxid=_own_wxid() or None,
    )
    status = 200 if result.get('ok') else 400
    return jsonify(result), status
