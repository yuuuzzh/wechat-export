"""Static guards for the non-technical search first-run experience."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "src/web/templates/search.html"
APP_JS = ROOT / "src/web/static/js/search-app.js"
APP_CSS = ROOT / "src/web/static/css/app.css"


def test_advanced_syntax_is_hidden_behind_the_existing_toggle():
    html = TEMPLATE.read_text(encoding="utf-8")
    assert 'id="search-help-toggle"' in html
    assert 'aria-controls="search-advanced"' in html
    assert 'id="search-advanced" style="display:none"' in html
    assert html.index('id="search-advanced"') < html.index('id="search-syntax"')


def test_first_run_and_empty_states_offer_real_next_actions():
    html = TEMPLATE.read_text(encoding="utf-8")
    js = APP_JS.read_text(encoding="utf-8")

    assert "从一个关键词开始" in html
    assert "st.source_shards === 0" in js
    assert "st.source_rows === 0" in js
    assert "一键构建（约 1 分钟，视机器与负载）" in js
    assert 'href="/backup"' in js
    assert "search-clear-filters" in js


def test_search_path_uses_inline_notices_instead_of_alerts():
    assert "alert(" not in APP_JS.read_text(encoding="utf-8")


def test_guidance_styles_use_scoped_prefixes():
    css = APP_CSS.read_text(encoding="utf-8")
    assert ".search-guide {" in css
    assert ".search-index-cta {" in css
