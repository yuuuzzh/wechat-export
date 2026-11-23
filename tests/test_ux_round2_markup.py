# -*- coding: utf-8 -*-
"""Static markup contracts for round-2 UX polish."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding='utf-8')


def test_dashboard_recent_strip():
    html = _read('src/web/templates/dashboard.html')
    assert 'id="dashboard-recent"' in html
    assert '最近使用' in html
    assert 'dash-recent-chats' in html


def test_search_simple_first_advanced_collapsed():
    html = _read('src/web/templates/search.html')
    assert 'id="search-advanced"' in html
    assert 'display:none' in html
    assert '从一个关键词开始' in html
    assert '例如：维修、年会照片、项目名称' in html


def test_backup_human_stage_labels():
    html = _read('src/web/templates/backup.html')
    assert '查找微信数据' in html
    assert '准备快速搜索' in html
    assert 'humanizeBackupDetail' in html
    assert 'detailFormatter: humanizeBackupDetail' in html


def test_cleanup_requires_ack_and_delete():
    js = _read('src/web/static/js/components/cleanup-confirm.js')
    assert 'id="cleanup-ack"' in js
    assert "el.value !== 'DELETE'" in js
    assert '文字聊天记录会保留' in js


def test_media_integrity_confirm_panel():
    html = _read('src/web/templates/media_integrity.html')
    assert 'id="media-confirm-panel"' in html
    assert 'media-confirm-ack' in html
    assert "alert('体检失败" not in html


def test_versions_empty_cta():
    html = _read('src/web/templates/versions.html')
    assert '去一键备份' in html
    assert 'id="versions-inline-msg"' in html
