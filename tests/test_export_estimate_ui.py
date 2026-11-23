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
