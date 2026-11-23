# -*- coding: utf-8 -*-
"""Static markup contracts for dashboard scenario shortcuts."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_scenario_shortcuts_are_inside_ready_user_strip():
    html = (ROOT / 'src/web/templates/dashboard.html').read_text(encoding='utf-8')
    recent_start = html.index('id="dashboard-recent"')
    recent_end = html.index('</section>', recent_start)
    recent_markup = html[recent_start:recent_end]

    assert '导出和某人的聊天' in recent_markup
    assert 'href="/export"' in recent_markup
    assert '群聊日报' in recent_markup
    assert 'href="/group"' in recent_markup
    assert '语音留给家人' in recent_markup
    assert 'href="/voice-export"' in recent_markup
