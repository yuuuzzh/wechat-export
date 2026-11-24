# -*- coding: utf-8 -*-
"""Mac manual-keys newbie guide wiring."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding='utf-8')


def test_mac_keys_guide_template_is_interactive():
    html = _read('src/web/templates/mac_keys_guide.html')
    assert '先选你的情况' in html
    assert 'have_backup' in html
    assert 'have_keys' in html
    assert 'mac_only' in html
    assert '不能一键从微信进程提取密钥' in html
    assert '/keys' in html
    assert 'message_0.db' in html


def test_mac_keys_guide_route_registered():
    app_py = _read('src/web/app.py')
    assert "/mac-keys-guide" in app_py
    assert 'mac_keys_guide.html' in app_py


def test_standalone_html_doc_exists():
    doc = _read('docs/mac-keys-guide.html')
    assert 'Mac 手动密钥新手指引' in doc
    assert 'have_backup' in doc
    assert '[Cipher-FOUND]' in doc or 'Cipher-FOUND' in doc


def test_entry_points_link_to_guide():
    assert '/mac-keys-guide' in _read('src/web/static/js/mac_guide.js')
    assert '/mac-keys-guide' in _read('src/web/templates/keys.html')
    assert 'mac-keyscan-redirect' in _read('src/web/templates/keyscan.html')
    assert 'mac_keys_guide' in _read('src/web/routes/setup_api.py')
    assert 'data-mac-only-card' in _read('src/web/templates/dashboard.html')
