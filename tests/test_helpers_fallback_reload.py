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

    # Restore to current environment. Reloading helpers creates fresh class
    # objects (NodeType, Node, ...) which desynchronize parmoji.core: it still
    # references the pre-reload helpers via its module globals, so later tests'
    # `node.type is NodeType.emoji` checks would compare two different enum
    # objects and silently fail (emojis parsed as text). Reload core too so its
    # helpers-backed names (NodeType, to_nodes) re-bind to the restored module.
    importlib.reload(H)
    import parmoji.core as _core

    importlib.reload(_core)


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
