# -*- coding: utf-8 -*-
"""Mac usage guide wiring: manual routes + the advanced one-click route."""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))


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


def test_advanced_route_has_six_step_wizard():
    html = _read('src/web/templates/mac_keys_guide.html')
    assert "choiceBtn('mac_advanced'" in html
    assert "mac_advanced: 'Mac 高级一键提钥'" in html
    for fn in ('advancedOverviewHtml', 'advancedHelperHtml', 'advancedSipHtml',
               'advancedWechatHtml', 'advancedRunHtml', 'advancedTroubleshootHtml'):
        assert fn in html, f'missing step: {fn}'
    assert 'mac-keys-go-keyscan' in html
    assert 'csrutil disable' in html and 'csrutil enable' in html
    assert 'SIP_ENABLED' in html and 'SCAN_FAILED' in html
    assert 'prepare_mac_key_helper.sh' in html


def test_offline_guide_covers_advanced_mode():
    doc = _read('docs/mac-keys-guide.html')
    assert "choice('mac_advanced'" in doc
    assert 'advancedRun()' in doc and 'prepare_mac_key_helper.sh' in doc
    assert 'csrutil enable' in doc and '4.1.13.8' in doc
    assert 'docs/mac-auto-key.md' in doc


def test_guide_route_renders_advanced_route():
    from web.app import create_app
    with tempfile.TemporaryDirectory(prefix='wb_guide_') as tmp:
        dec = Path(tmp) / 'dec'
        (dec / 'message').mkdir(parents=True)
        app = create_app(str(dec), wxid='wxid_owner')
        app.config['TESTING'] = True
        resp = app.test_client().get('/mac-keys-guide')
        assert resp.status_code == 200
        html = resp.data.decode('utf-8')
        assert "choiceBtn('mac_advanced'" in html
        assert 'advancedTroubleshootHtml' in html


def test_advanced_entry_points_point_to_usage_guide():
    for rel in ('src/web/templates/keyscan.html',
                'src/web/templates/keys.html',
                'src/web/templates/setup.html',
                'src/web/templates/dashboard.html'):
        assert 'Mac 使用新手指引' in _read(rel), rel
    dashboard = _read('src/web/templates/dashboard.html')
    assert "href: '/mac-keys-guide'" in dashboard
    assert 'keysMacAdvanced' in dashboard
    assert 'Mac 使用新手指引（高级模式 6 步）' in _read('src/web/templates/keyscan.html')
    assert '使用新手指引' in _read('docs/mac-auto-key.md')
