# -*- coding: utf-8 -*-
"""Workspace switcher + first-time setup status APIs."""
from __future__ import annotations

import os
import sys

ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(ROOT, 'src'))


def test_setup_and_workspace_endpoints():
    from web.app import create_app
    app = create_app(decrypted_dir=os.path.join(ROOT, 'no_such'))
    cli = app.test_client()

    r = cli.get('/api/setup/status')
    assert r.status_code == 200
    data = r.get_json()
    assert data['ok']
    assert 'steps' in data
    assert len(data['steps']) >= 3

    r2 = cli.get('/api/workspace')
    assert r2.status_code == 200
    w = r2.get_json()
    assert w['ok']
    assert 'accounts' in w
    assert 'ready' in w

    r3 = cli.get('/setup')
    assert r3.status_code == 200
    assert '首次'.encode('utf-8') in r3.data or b'setup' in r3.data.lower()
