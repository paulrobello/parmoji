from __future__ import annotations

from io import BytesIO

import pytest
from PIL import Image

from parmoji.core import LRUCacheDict, Parmoji


class _ExplodingClose:
    def close(self):  # noqa: D401
        raise RuntimeError("boom")


@pytest.mark.parmoji
def test_lru_close_exceptions_are_suppressed():
    lru = LRUCacheDict(maxsize=1)
    lru["a"] = _ExplodingClose()
    # Inserting another key evicts "a" and attempts to close, which raises but is suppressed
    lru["b"] = BytesIO(b"x")
    assert "a" not in lru
    assert "b" in lru


@pytest.mark.parmoji
def test_prepare_text_params_defaults():
    img = Image.new("RGBA", (10, 10), (0, 0, 0, 0))
    p = Parmoji(img, cache=False)
    # Pass all None to trigger default font, default offsets, and draw creation
    font, scale, offset, draw = p._prepare_text_params(None, None, None)  # type: ignore[attr-defined]
    assert font is not None and draw is not None
    assert isinstance(scale, float)
    assert isinstance(offset, tuple) and len(offset) == 2
