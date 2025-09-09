from __future__ import annotations

from pathlib import Path
from io import BytesIO

import pytest

from parmoji.local_source import LocalFontSource


@pytest.mark.parmoji
def test_local_source_disk_cache_roundtrip_and_clear(tmp_path: Path):
    # Avoid prime_on_init to keep test fast
    src = LocalFontSource(disk_cache=True, prime_on_init=False)

    # Render once; should produce a PNG and save to cache
    s1 = src.get_emoji("😀")
    assert isinstance(s1, BytesIO)
    assert src._cache_dir is not None
    cached_files = list(src._cache_dir.glob("*.png"))
    assert cached_files, "expected at least one cached file"

    # Second time should load from cache
    s2 = src.get_emoji("😀")
    assert isinstance(s2, BytesIO)

    # Clear cache
    src.clear_cache()
    assert src._cache_dir is not None
    assert list(src._cache_dir.glob("*.png")) == []


@pytest.mark.parmoji
def test_local_source_disk_cache_read_error(monkeypatch, tmp_path: Path):
    # Enable disk cache and create a bogus PNG to trigger read path
    src = LocalFontSource(disk_cache=True, prime_on_init=False)
    emj = "😀"
    assert src._cache_dir is not None
    cache_key = src._get_cache_key(emj)
    cache_file = src._cache_dir / f"{cache_key}.png"
    cache_file.write_bytes(b"not a real png")

    # Force Path.read_bytes to raise for this file to hit the except branch
    import pathlib

    real_read = pathlib.Path.read_bytes

    def _read_bytes(self):  # type: ignore[override]
        if self == cache_file:
            raise OSError("cannot read")
        return real_read(self)

    monkeypatch.setattr(pathlib.Path, "read_bytes", _read_bytes, raising=False)
    stream = src.get_emoji(emj)
    # Should fall back to render path and return a valid stream
    from io import BytesIO

    assert isinstance(stream, BytesIO)


@pytest.mark.parmoji
def test_local_source_save_to_cache_error(monkeypatch):
    src = LocalFontSource(disk_cache=True, prime_on_init=False)
    # Make write_bytes raise to exercise error path
    import pathlib

    real_write = pathlib.Path.write_bytes

    def _write_bytes(self, data):  # type: ignore[override]
        if self.suffix == ".png":
            raise OSError("disk full")
        return real_write(self, data)

    monkeypatch.setattr(pathlib.Path, "write_bytes", _write_bytes, raising=False)
    stream = src.get_emoji("😀")
    from io import BytesIO

    assert isinstance(stream, BytesIO)


@pytest.mark.parmoji
def test_local_source_outer_exception_path(monkeypatch):
    # Force ImageDraw.Draw to raise so outer try/except triggers
    src = LocalFontSource(disk_cache=False, prime_on_init=False)

    def _raise_draw(*a, **k):  # noqa: ANN001
        raise RuntimeError("boom")

    monkeypatch.setattr("parmoji.local_source.ImageDraw.Draw", _raise_draw)
    # With the test autouse fallback, a minimal PNG is returned instead of None
    from io import BytesIO

    assert isinstance(src.get_emoji("😀"), BytesIO)


@pytest.mark.parmoji
def test_local_source_prime_on_init_calls_prime(monkeypatch):
    called = {"n": 0}

    def _prime(self, emojis=None):  # noqa: ANN001
        called["n"] += 1

    monkeypatch.setattr("parmoji.source.BaseSource.prime_cache", _prime)
    _ = LocalFontSource(disk_cache=True, prime_on_init=True)
    assert called["n"] >= 1


@pytest.mark.parmoji
def test_local_source_clear_cache_no_dir():
    # When _cache_dir is None, the function should exit quietly
    src = LocalFontSource(disk_cache=False, prime_on_init=False)
    # Ensure no exception
    src.clear_cache()


@pytest.mark.parmoji
def test_local_source_discord_emoji_not_supported():
    src = LocalFontSource(disk_cache=False, prime_on_init=False)
    assert src.get_discord_emoji(123) is None
    assert "LocalFontSource" in repr(src)
