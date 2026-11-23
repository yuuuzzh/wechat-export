# -*- coding: utf-8 -*-
"""Console tip wiring for Windows users."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_console_tip_assets_wired():
    tip = (ROOT / 'src/web/static/js/console_tip.js').read_text(encoding='utf-8')
    base = (ROOT / 'src/web/templates/base.html').read_text(encoding='utf-8')
    dash = (ROOT / 'src/web/templates/dashboard.html').read_text(encoding='utf-8')
    bat = (ROOT / 'start.bat').read_text(encoding='utf-8')
    assert 'wechat-export-console-tip-dismissed' in tip
    assert '黑窗口是正常的' in tip
    assert 'js/console_tip.js' in base
    assert 'data-console-tip' in dash
    assert 'black console window is normal' in bat.lower() or 'Do not close' in bat or 'keep it open' in bat
