from __future__ import annotations

import hashlib
from io import BytesIO

import pytest
from PIL import Image

from parmoji.source import TwitterEmojiSource


class _TightCDN(TwitterEmojiSource):
    """TwitterEmojiSource that returns a synthetic PNG with transparent padding."""

    def __init__(self, png_bytes: bytes, *a, **k):
        super().__init__(*a, **k)
        self._png = png_bytes
        self.requests = 0

    def request(self, url: str) -> bytes:  # type: ignore[override]
        self.requests += 1
        return self._png


def _make_padded_png(size: int = 64, border: int = 10) -> bytes:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    inner = Image.new("RGBA", (size - 2 * border, size - 2 * border), (255, 0, 0, 255))
    img.paste(inner, (border, border))
    b = BytesIO()
    img.save(b, format="PNG")
    return b.getvalue()


@pytest.mark.parmoji
def test_tight_cropping_and_cache_derivation(tmp_path, monkeypatch):
    # Ensure cache goes to a temp dir
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))

    data = _make_padded_png(size=64, border=10)
    s = _TightCDN(data, disk_cache=True)
    emj = "😀"

    # Request with tight=True should crop from 64x64 with 10px border -> 44px
    # margin=2 expands by 2 on each side -> 48px
    out = s.get_emoji(emj, tight=True, margin=2)
    assert out is not None
    im = Image.open(out)
    assert im.size == (48, 48)

    # Both raw and tight cache files should exist
    raw_key = hashlib.md5(f"{emj}_{s.STYLE}".encode()).hexdigest()
    t_key = hashlib.md5(f"{emj}_{s.STYLE}_t2".encode()).hexdigest()
    assert (s._cache_dir / f"{raw_key}.png").exists()  # type: ignore[arg-type]
    assert (s._cache_dir / f"{t_key}.png").exists()  # type: ignore[arg-type]

    # Subsequent request should load from tight cache even if network fails
    def _fail(_url: str) -> bytes:  # noqa: ARG001
        raise RuntimeError("no network")

    s.request = _fail  # type: ignore[assignment]
    out2 = s.get_emoji(emj, tight=True, margin=2)
    assert out2 is not None
    im2 = Image.open(out2)
    assert im2.size == (48, 48)

    # Remove derived cache, ensure it can be rebuilt from raw cache without network
    (s._cache_dir / f"{t_key}.png").unlink()  # type: ignore[arg-type]
    out3 = s.get_emoji(emj, tight=True, margin=2)
    assert out3 is not None
    im3 = Image.open(out3)
    assert im3.size == (48, 48)


@pytest.mark.parmoji
def test_env_default_tight(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("PARMOJI_TIGHT", "1")
    monkeypatch.setenv("PARMOJI_TIGHT_MARGIN", "2")

    data = _make_padded_png(size=64, border=10)
    s = _TightCDN(data, disk_cache=True)

    out = s.get_emoji("😀")  # no explicit tight args -> env applies
    assert out is not None
    im = Image.open(out)
    assert im.size == (48, 48)
