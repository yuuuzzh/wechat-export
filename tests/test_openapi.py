# -*- coding: utf-8 -*-
"""OpenAPI document is generated from the live Flask map."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src'))

from web.app import create_app
from web.openapi_spec import build_openapi


def test_openapi_covers_registered_api(tmp_path):
    app = create_app(decrypted_dir=str(tmp_path))
    spec = build_openapi(app, version='test')
    assert spec['openapi'].startswith('3.')
    assert spec['info']['title']
    paths = spec['paths']
    assert '/api/contacts' in paths
    assert 'get' in paths['/api/contacts']
    assert '/api/specials/status' in paths
    assert '/api/backup/versions' in paths
    assert '/api/openapi.json' not in paths

    msg = paths['/api/messages/{msg_id}']['get']
    names = [p['name'] for p in msg['parameters'] if p['in'] == 'path']
    assert names == ['msg_id']
    assert msg['parameters'][0]['schema']['type'] == 'integer'

    chat = paths['/api/export/chat']['post']
    assert 'requestBody' in chat
    assert chat['responses']['200']['content'].get('text/event-stream')


def test_openapi_http(tmp_path):
    app = create_app(decrypted_dir=str(tmp_path))
    cli = app.test_client()
    r = cli.get('/api/openapi.json')
    assert r.status_code == 200
    body = r.get_json()
    assert body['paths']['/api/sns/status']['get']['summary']
    page = cli.get('/swagger')
    assert page.status_code == 200
    assert b'/api/openapi.json' in page.data
