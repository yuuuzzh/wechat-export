# -*- coding: utf-8 -*-
"""Static markup contracts for the UX onboarding / nav / export layering work."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding='utf-8')


def test_dashboard_has_onboarding_shell():
    html = _read('src/web/templates/dashboard.html')
    assert 'id="dashboard-onboarding"' in html
    assert 'id="dashboard-all-features"' in html
    assert "/api/setup/status" in html
    assert '查看全部功能' in html


def test_setup_has_sticky_next_action():
    html = _read('src/web/templates/setup.html')
    assert 'id="setup-next-bar"' in html
    assert '一键去完成下一步' in html
    assert 'id="setup-wechat-status"' in html


def test_export_format_optgroups_and_inline_error():
    html = _read('src/web/templates/export.html')
    assert 'optgroup label="常用"' in html
    assert 'optgroup id="advanced-format-options" label="更多格式"' in html
    assert 'id="export-inline-error"' in html
    assert "alert('请先在列表中勾选" not in html
    assert '去一键备份' in html
    assert 'wechat-export-default-export-format' in html


def test_settings_prefs_keys():
    html = _read('src/web/templates/settings.html')
    assert 'id="prefs-panel"' in html
    assert 'wechat-export-default-export-format' in html
    assert 'wechat-export-backup-days-pref' in html
