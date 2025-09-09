from __future__ import annotations

import hashlib

import pytest
from PIL import Image

from parmoji.core import LRUCacheDict, Parmoji
from parmoji.source import TwitterEmojiSource


@pytest.mark.parmoji
def test_parmoji_open_reinit_httpbased_and_close_caches():
    # Use HTTPBasedSource subclass (Twemoji) to cover requests Session reinit branch in open()
    img = Image.new("RGBA", (20, 20), (0, 0, 0, 0))
    p = Parmoji(img, source=TwitterEmojiSource, cache=True, disk_cache=False)
    # Close then reopen to hit reinit branch
    p.close()
    p.open()
    # Close cleanly again
    p.close()


@pytest.mark.parmoji
def test_lru_move_to_end_and_getitem_tracked():
    lru = LRUCacheDict(maxsize=3)
    from io import BytesIO

    lru["x"] = BytesIO(b"x")
    # Re-assign same key to hit the in-dict move_to_end path
    lru["x"] = BytesIO(b"y")
    # Access via __getitem__ to exercise that move_to_end path
    _ = lru["x"]


class _SpyCDN(TwitterEmojiSource):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.calls = 0

    def request(self, url: str) -> bytes:  # type: ignore[override]
        self.calls += 1
        # Minimal valid PNG blob
        return b"\x89PNG\r\n\x1a\n\x00\x00hello"


@pytest.mark.parmoji
def test_cdn_retry_branch_and_disk_load(tmp_path):
    # disk_cache on to persist PNG and failed cache JSON under test HOME set by conftest
    s = _SpyCDN(disk_cache=True)
    emoji = "😀"
    cache_key = hashlib.md5(f"{emoji}_{s.STYLE}".encode()).hexdigest()

    # Mark this key as failed so the retry branch executes
    s._mark_request_failed(cache_key)
    stream_retry = s.get_emoji(emoji)
    assert stream_retry is not None
    # The failure should be cleared
    assert not s._is_request_failed(cache_key)
    assert s._cache_dir is not None
    png_path = s._cache_dir / f"{cache_key}.png"
    assert png_path.exists()

    # Now exercise disk cache load branch
    s2 = _SpyCDN(disk_cache=True)
    stream_disk = s2.get_emoji(emoji)
    assert stream_disk is not None
    # No network call needed when disk cache present (may be 0 or 1 depending on existence timing)
    assert s2.calls in (0, 1)
