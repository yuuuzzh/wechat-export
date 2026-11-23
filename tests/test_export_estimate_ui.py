# -*- coding: utf-8 -*-
"""导出页消息量预估的轻量静态契约。"""
from pathlib import Path


TEMPLATE = (
    Path(__file__).resolve().parents[1]
    / 'src' / 'web' / 'templates' / 'export.html'
)


def _template():
    return TEMPLATE.read_text(encoding='utf-8')


def test_export_estimate_uses_selected_chat_counts_client_side():
    text = _template()
    assert 'id="sel-summary"' in text
    assert 'aria-live="polite"' in text
    assert 'Number(c.msg_count || 0)' in text
    assert "total.toLocaleString() + ' 条消息 · 已选 '" in text
    assert '/api/export/estimate' not in text


def test_export_estimate_discloses_unapplied_filters_and_refreshes():
    text = _template()
    assert '列表合计约 ' in text
    assert '（未计关键词/日期过滤）' in text
    assert "keywordInput.addEventListener('input', updateSummary)" in text
    assert "startInput.addEventListener('change', updateSummary)" in text
    assert "endInput.addEventListener('change', updateSummary)" in text


def test_export_estimate_includes_rough_duration_bands():
    text = _template()
    assert "total < 1000 ? '约几秒'" in text
    assert "total < 10000 ? '不到一分钟'" in text
    assert "'可能要几分钟'" in text
    assert "eta.className = 'export-eta'" in text


def test_recent_exports_are_persisted_and_rendered():
    text = _template()
    assert 'id="export-history"' in text
    assert "const historyKey = 'wechat-export-recent-exports'" in text
    assert 'entries.unshift({' in text
    assert 'entries.slice(0, 5)' in text
    assert 'download_url: usefulDownloadUrl(result.download_url)' in text
    assert 'page.showResult = function (result)' in text
