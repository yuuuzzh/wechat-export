# -*- coding: utf-8 -*-
"""Static contracts for consistent missing-media guidance in chat."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_shared_media_callout_has_recovery_links():
    image_js = _read("src/web/static/js/image-fallback.js")
    # JS string literals escape quotes: href=\"/media-integrity\"
    assert "/media-integrity" in image_js
    assert "/backup" in image_js
    assert "callout: callout" in image_js
    assert "media-miss-callout" in image_js


def test_image_and_voice_failures_use_shared_callout():
    bubbles_js = _read("src/web/static/js/components/message-bubble.js")
    voice_js = _read("src/web/static/js/components/voice-player.js")
    assert 'data-media-error="${isWx4?\'v2\':\'\'}"' in bubbles_js
    assert bubbles_js.count("ImageFallback.callout(") >= 3
    assert "_showMediaError(msgId)" in voice_js
    assert "ImageFallback.callout(" in voice_js
    assert "在微信中打开对应聊天" in voice_js
