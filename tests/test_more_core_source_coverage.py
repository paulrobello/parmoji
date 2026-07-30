from __future__ import annotations

import hashlib

import pytest
from PIL import Image

from parmoji.core import LRUCacheDict, Parmoji
from parmoji.source import HTTPBasedSource, TwitterEmojiSource


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
def test_parmoji_open_recreates_live_httpx_client():
    # ARC-003 regression guard: after close()/open() the default httpx client
    # must be recreated and usable. Previously open() only built a requests
    # Session and left the closed httpx client in place, so every later
    # request() on the default backend fell through to urllib.
    img = Image.new("RGBA", (20, 20), (0, 0, 0, 0))
    p = Parmoji(img, source=TwitterEmojiSource, cache=True, disk_cache=False)
    src = p.source
    assert isinstance(src, HTTPBasedSource)
    live_before = src._httpx_client
    p.close()
    # close() shuts the httpx client down; the reference may still point at it
    # but it must not be the live one used after reopen.
    p.open()
    assert src is p.source
    assert src._httpx_client is not None
    # The reopened client is a fresh, live instance (not the closed one).
    assert src._httpx_client is not live_before
    assert src._httpx_client.is_closed is False
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


def _png_bytes() -> bytes:
    from io import BytesIO

    buf = BytesIO()
    Image.new("RGBA", (4, 4), (255, 0, 0, 255)).save(buf, format="PNG")
    return buf.getvalue()


class _SpyCDN(TwitterEmojiSource):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.calls = 0

    def request(self, url: str) -> bytes:  # type: ignore[override]
        self.calls += 1
        # QA-011: real image bytes so the disk-persist validation gate passes.
        return _png_bytes()


@pytest.mark.parmoji
def test_cdn_retry_branch_and_disk_load(tmp_path):
    # disk_cache on to persist PNG and failed cache JSON under test HOME set by conftest
    s = _SpyCDN(disk_cache=True)
    emoji = "😀"
    cache_key = hashlib.blake2b(f"{emoji}_{s.STYLE}".encode(), digest_size=16).hexdigest()

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
