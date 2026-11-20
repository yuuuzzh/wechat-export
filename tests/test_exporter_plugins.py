# -*- coding: utf-8 -*-
"""Drop-in exporter plugins."""
from __future__ import annotations

import os
import sys

ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(ROOT, 'src'))

from engine.services import exporter_plugins as ep  # noqa: E402


def test_discover_example_plugin():
    plugins = ep.discover_plugins(force=True)
    assert 'example-jsonl' in plugins
    p = plugins['example-jsonl']
    assert callable(p['export'])


def test_run_example_plugin(tmp_path):
    out = str(tmp_path / 'out.jsonl')
    msgs = [{
        'timestamp': '2023-01-01 00:00:00',
        'sender': 'a',
        'chat_name': 'c',
        'type_name': '文本',
        'text': 'hi',
    }]
    path = ep.run_plugin('example-jsonl', msgs, {'display': 't'}, out)
    assert os.path.isfile(path)
    text = open(path, encoding='utf-8').read()
    assert 'hi' in text
    assert 'meta' in text


def test_formats_api_includes_plugins():
    from web.app import create_app
    app = create_app(decrypted_dir=os.path.join(ROOT, 'no_such'))
    cli = app.test_client()
    r = cli.get('/api/export/formats')
    assert r.status_code == 200
    data = r.get_json()
    assert data['ok']
    plugin_fmts = {p['format'] for p in data.get('plugins') or []}
    assert 'example-jsonl' in plugin_fmts
    builtin = {b['format'] for b in data.get('builtin') or []}
    assert 'eml' in builtin and 'mbox' in builtin
