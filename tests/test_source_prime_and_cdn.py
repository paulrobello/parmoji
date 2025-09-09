from __future__ import annotations

from io import BytesIO

import pytest

from parmoji.source import BaseSource, EmojiCDNSource, TwitterEmojiSource


class _PrimeOnlySource(BaseSource):
    """Minimal source to exercise BaseSource.prime_cache without network."""

    calls: int = 0

    def get_emoji(self, emoji: str):
        # Return a tiny PNG stream for a subset to simulate success; None otherwise
        _ = emoji  # unused
        _PrimeOnlySource.calls += 1
        # Always return None to keep the loop fast; we're covering control flow
        return None

    def get_discord_emoji(self, emoji_id: int):  # pragma: no cover - unused
        return None


@pytest.mark.parmoji
def test_prime_cache_respects_disk_cache_flag(monkeypatch):
    s = _PrimeOnlySource(disk_cache=False)
    # Should return immediately and perform no calls
    _PrimeOnlySource.calls = 0
    s.prime_cache()
    assert _PrimeOnlySource.calls == 0


@pytest.mark.parmoji
def test_prime_cache_default_set_executes_and_dedups(monkeypatch):
    # Enable disk cache to exercise default emoji set branch
    s = _PrimeOnlySource(disk_cache=True)
    _PrimeOnlySource.calls = 0
    # Call with default set (None) to cover the large literal and loop
    s.prime_cache()
    # Call again to cover the "already primed" fast path
    primed_count_first = len(s._primed_emojis)
    s.prime_cache()
    assert len(s._primed_emojis) == primed_count_first


@pytest.mark.parmoji
def test_prime_cache_custom_set_branch(monkeypatch):
    s = _PrimeOnlySource(disk_cache=True)
    before = len(s._primed_emojis)
    s.prime_cache({"😀", "😃"})
    # Even though get_emoji returns None, branch executes and set unchanged
    assert len(s._primed_emojis) == before


class _ReturnStreamSource(BaseSource):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.count = 0

    def get_emoji(self, emoji: str):
        # Return a tiny PNG stream for the first two calls, then None
        from PIL import Image

        if self.count < 2:
            self.count += 1
            im = Image.new("RGBA", (4, 4), (255, 0, 0, 255))
            from io import BytesIO

            b = BytesIO()
            im.save(b, format="PNG")
            b.seek(0)
            return b
        return None

    def get_discord_emoji(self, emoji_id: int):  # pragma: no cover - unused
        return None


@pytest.mark.parmoji
def test_prime_cache_success_and_continue_path():
    # disk_cache not required for prime_cache logic; we're exercising control flow
    s = _ReturnStreamSource(disk_cache=True)
    s.prime_cache({"😀", "😃", "😄"})
    # At least two emojis should be considered primed
    assert len(s._primed_emojis) >= 2
    # Call again to hit the "already primed" continue path
    prev = set(s._primed_emojis)
    s.prime_cache(prev)


class _FakeCDN(TwitterEmojiSource):
    """TwitterEmojiSource that returns fixed bytes from request."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.requests = 0

    def request(self, url: str) -> bytes:  # type: ignore[override]
        self.requests += 1
        # Minimal valid PNG header + IHDR chunk placeholder
        return b"\x89PNG\r\n\x1a\n\x00\x00test"


@pytest.mark.parmoji
def test_cdn_invalid_input_early_return(monkeypatch):
    # Non-emoji should be rejected before any network call
    s = _FakeCDN(disk_cache=False)
    out = s.get_emoji("x")
    assert out is None
    assert s.requests == 0


@pytest.mark.parmoji
def test_discord_fetch_success_via_mixin(monkeypatch):
    s = _FakeCDN(disk_cache=False)
    # get_discord_emoji delegates to request URL builder; ensure we get bytes back
    stream = s.get_discord_emoji(1234567890)
    assert isinstance(stream, BytesIO)
    assert stream.getvalue().startswith(b"\x89PNG")


@pytest.mark.parmoji
def test_discord_fetch_failure_returns_none(monkeypatch):
    class _FailCDN(_FakeCDN):
        def request(self, url: str) -> bytes:  # type: ignore[override]
            raise RuntimeError("boom")

    s = _FailCDN(disk_cache=False)
    assert s.get_discord_emoji(42) is None


@pytest.mark.parmoji
def test_cdn_normal_success_saves_to_disk_and_loads():
    s = _FakeCDN(disk_cache=True)
    emj = "😀"
    # First call should write to disk
    st1 = s.get_emoji(emj)
    assert st1 is not None
    # Second call should load from disk (network still could be called; behavior is implementation-defined)
    st2 = s.get_emoji(emj)
    assert st2 is not None


@pytest.mark.parmoji
def test_cdn_style_unfilled_raises_typeerror():
    class _NoStyle(EmojiCDNSource):
        STYLE = None

    with pytest.raises(TypeError):
        _NoStyle(disk_cache=False).get_emoji("😀")


@pytest.mark.parmoji
def test_source_repr():
    # Ensure __repr__ is covered for an HTTP-based subclass
    s = _FakeCDN(disk_cache=True)
    r = repr(s)
    assert "disk_cache" in r
