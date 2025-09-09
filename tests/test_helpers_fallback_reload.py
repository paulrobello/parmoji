from __future__ import annotations

import importlib

import pytest


@pytest.mark.parmoji
def test_helpers_textlength_fallback_via_reload(monkeypatch):
    import PIL
    import parmoji.helpers as H

    # Force HAS_GETLENGTH False by simulating older Pillow
    monkeypatch.setattr(PIL, "__version__", "8.0.0", raising=False)
    H2 = importlib.reload(H)
    w, h = H2.getsize("abc")
    assert w > 0 and h > 0

    # Restore to current environment
    importlib.reload(H)


@pytest.mark.parmoji
def test_helpers_getsize_modern_path():
    import parmoji.helpers as H
    from PIL import ImageFont

    w, h = H.getsize("abc", font=ImageFont.load_default())
    assert w > 0 and h > 0


@pytest.mark.parmoji
def test_helpers_getsize_emoji_triggers_constant_width():
    import parmoji.helpers as H
    from PIL import ImageFont

    w1, _ = H.getsize("😀", font=ImageFont.load_default(), emoji_scale_factor=1.0)
    w2, _ = H.getsize("😀", font=ImageFont.load_default(), emoji_scale_factor=2.0)
    assert w2 > w1
