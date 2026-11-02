# -*- coding: utf-8 -*-
"""Year-over-year comparison."""
from __future__ import annotations

import os
import sys
from datetime import datetime

ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(ROOT, 'src'))

from engine.constants import TZ  # noqa: E402
from engine.services import yoy as y  # noqa: E402


def test_year_bounds():
    t0, t1 = y._year_bounds(2024)
    assert datetime.fromtimestamp(t0, tz=TZ).year == 2024
    assert datetime.fromtimestamp(t1, tz=TZ).year == 2025


def test_fold_and_compare(monkeypatch, tmp_path):
    # Synthetic rows for 2024 and 2025
    def fake_index(decrypted_dir, year, **kwargs):
        t0, t1 = y._year_bounds(year)
        mid = (t0 + t1) // 2
        if year == 2025:
            rows = [
                ('wxid_a', 1, mid, 'me'),
                ('wxid_a', 1, mid + 10, 'other'),
                ('room@chatroom', 34, mid + 20, 'other'),
            ]
        else:
            rows = [
                ('wxid_a', 1, mid, 'me'),
            ]
        return y._fold_rows(rows, year, {'me'}, top_chats_n=5), None

    monkeypatch.setattr(y, '_collect_from_index', fake_index)
    monkeypatch.setattr(y, '_enrich_top_chats', lambda *a, **k: None)
    out = y.build_yoy_report(str(tmp_path), year=2025, own_wxid='me')
    assert out['ok']
    assert out['year'] == 2025 and out['prev_year'] == 2024
    assert out['current']['total'] == 3
    assert out['previous']['total'] == 1
    total_delta = next(d for d in out['deltas'] if d['key'] == 'total')
    assert total_delta['delta'] == 2


def test_api_yoy(monkeypatch, tmp_path):
    from web.app import create_app

    def fake_index(decrypted_dir, year, **kwargs):
        return y._empty_stats(year), None

    monkeypatch.setattr('engine.services.yoy._collect_from_index', fake_index)
    app = create_app(decrypted_dir=str(tmp_path))
    cli = app.test_client()
    assert cli.get('/yoy').status_code == 200
    r = cli.post('/api/yoy/compare', json={'year': 2026})
    j = r.get_json()
    assert r.status_code == 200 and j['ok']
