from __future__ import annotations

import pytest
from PIL import Image

from parmoji.core import LRUCacheDict, Parmoji


@pytest.mark.parmoji
def test_lru_eviction_drops_oldest_without_closing():
    # ARC-007: eviction no longer calls .close() on evicted values (the cache
    # stores immutable bytes). Evicting just drops the entry; an evicted value
    # that happens to be closeable is left untouched.
    lru = LRUCacheDict(maxsize=1)
    lru["a"] = b"bytes"
    lru["b"] = b"more"
    assert "a" not in lru
    assert "b" in lru
    assert lru.get("a") is None
    assert lru.get("b") == b"more"


@pytest.mark.parmoji
def test_prepare_text_params_defaults():
    img = Image.new("RGBA", (10, 10), (0, 0, 0, 0))
    p = Parmoji(img, cache=False)
    # Pass all None to trigger default font, default offsets, and draw creation
    font, scale, offset, draw = p._prepare_text_params(None, None, None)  # type: ignore[attr-defined]
    assert font is not None and draw is not None
    assert isinstance(scale, float)
    assert isinstance(offset, tuple) and len(offset) == 2
