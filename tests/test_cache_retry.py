from __future__ import annotations

import hashlib
from io import BytesIO

import pytest
from PIL import Image

from parmoji.source import TwitterEmojiSource


def _png_bytes(size=(8, 8), color=(255, 0, 0, 255)) -> bytes:
    img = Image.new("RGBA", size, color)
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class FlakySource(TwitterEmojiSource):
    calls: int = 0

    def request(self, url: str) -> bytes:  # type: ignore[override]
        # First call fails; second succeeds; subsequent not called thanks to disk cache
        FlakySource.calls += 1
        if FlakySource.calls == 1:
            raise RuntimeError("simulated network failure")
        return _png_bytes()


@pytest.mark.parmoji
def test_retry_clears_failed_cache_and_persists_disk_cache(tmp_path):
    # Use an emoji with stable CDN path
    emoji = "😀"

    # Ensure class counter is clean
    FlakySource.calls = 0

    # Enable disk cache so the persistent JSON and PNG files are created under HOME/.cache
    src = FlakySource(disk_cache=True)

    # Compute expected cache key filename
    cache_key = hashlib.md5(f"{emoji}_{src.STYLE}".encode()).hexdigest()
    assert src._cache_dir is not None  # disk cache enabled
    png_path = src._cache_dir / f"{cache_key}.png"
    failed_json = src._cache_dir / "failed_requests.json"

    try:
        # First attempt fails, should mark failed in JSON
        stream1 = src.get_emoji(emoji)
        assert stream1 is None
        assert FlakySource.calls == 1
        # failed_requests.json should exist and contain the key
        assert failed_json.exists()
        assert cache_key in failed_json.read_text()

        # Second attempt: code detects previous failure and retries once, then clears failure
        stream2 = src.get_emoji(emoji)
        assert stream2 is not None
        assert isinstance(stream2, BytesIO)
        assert FlakySource.calls == 2
        # The failure cache should be cleared for this key
        text = failed_json.read_text()
        assert cache_key not in text
        # The PNG should be persisted to disk cache
        assert png_path.exists()

        # Third attempt should hit disk cache and not perform network request
        stream3 = src.get_emoji(emoji)
        assert stream3 is not None
        assert FlakySource.calls == 2, "should not issue another network request when disk cache present"
    finally:
        src.close()
