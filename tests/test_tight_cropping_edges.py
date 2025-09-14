from __future__ import annotations

import hashlib
from io import BytesIO

import pytest
from PIL import Image

from parmoji.source import TwitterEmojiSource


def _make_padded_png(size: int = 64, border: int = 10, *, opaque: bool = False, transparent: bool = False) -> bytes:
    if transparent:
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    else:
        base_color = (255, 0, 0, 255 if opaque else 0)
        img = Image.new("RGBA", (size, size), base_color)

    if not transparent and not opaque:
        inner = Image.new("RGBA", (size - 2 * border, size - 2 * border), (0, 255, 0, 255))
        img.paste(inner, (border, border))
    b = BytesIO()
    img.save(b, format="PNG")
    return b.getvalue()


class _CDN(TwitterEmojiSource):
    def __init__(self, data: bytes, *a, **k):
        super().__init__(*a, **k)
        self._data = data
        self.calls = 0

    def request(self, url: str) -> bytes:  # type: ignore[override]
        self.calls += 1
        return self._data


@pytest.mark.parmoji
def test_tight_false_returns_original_dimensions(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    data = _make_padded_png(size=64, border=10)
    s = _CDN(data, disk_cache=True)
    out = s.get_emoji("😀", tight=False)
    assert out is not None
    im = Image.open(out)
    assert im.size == (64, 64)


@pytest.mark.parmoji
def test_negative_and_large_margin_clamped(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    data = _make_padded_png(size=64, border=10)
    s = _CDN(data, disk_cache=True)
    emj = "😀"

    # margin < 0 acts like 0 (alpha bbox only)
    out_neg = s.get_emoji(emj, tight=True, margin=-5)
    im_neg = Image.open(out_neg)  # type: ignore[arg-type]
    assert im_neg.size == (44, 44)  # 64 - 2*10

    # very large margin clamps to image bounds (not > 64)
    out_big = s.get_emoji(emj, tight=True, margin=1000)
    im_big = Image.open(out_big)  # type: ignore[arg-type]
    assert im_big.size == (64, 64)


@pytest.mark.parmoji
def test_opaque_image_returns_original(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    data = _make_padded_png(size=64, border=0, opaque=True)
    s = _CDN(data, disk_cache=True)
    out = s.get_emoji("😀", tight=True, margin=2)
    im = Image.open(out)  # type: ignore[arg-type]
    assert im.size == (64, 64)


@pytest.mark.parmoji
def test_fully_transparent_returns_original(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    data = _make_padded_png(size=64, border=0, transparent=True)
    s = _CDN(data, disk_cache=True)
    out = s.get_emoji("😀", tight=True, margin=2)
    im = Image.open(out)  # type: ignore[arg-type]
    assert im.size == (64, 64)


@pytest.mark.parmoji
def test_failed_request_retry_clears_flag(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    data = _make_padded_png(size=64, border=10)
    s = _CDN(data, disk_cache=True)
    emj = "😀"

    # Pre-mark as failed
    base_key = hashlib.md5(f"{emj}_{s.STYLE}".encode()).hexdigest()
    s._failed_requests.add(base_key)  # type: ignore[attr-defined]

    out = s.get_emoji(emj, tight=True, margin=1)
    assert out is not None
    # Should be cleared on success
    assert base_key not in s._failed_requests  # type: ignore[attr-defined]


@pytest.mark.parmoji
def test_margin_affects_cache_key(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    data = _make_padded_png(size=64, border=10)
    s = _CDN(data, disk_cache=True)
    emj = "😀"

    out1 = s.get_emoji(emj, tight=True, margin=1)
    out5 = s.get_emoji(emj, tight=True, margin=5)
    assert out1 is not None and out5 is not None

    k1 = hashlib.md5(f"{emj}_{s.STYLE}_t1".encode()).hexdigest()
    k5 = hashlib.md5(f"{emj}_{s.STYLE}_t5".encode()).hexdigest()
    assert (s._cache_dir / f"{k1}.png").exists()  # type: ignore[arg-type]
    assert (s._cache_dir / f"{k5}.png").exists()  # type: ignore[arg-type]


@pytest.mark.parmoji
def test_env_off_does_not_apply(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("PARMOJI_TIGHT", "off")

    data = _make_padded_png(size=64, border=10)
    s = _CDN(data, disk_cache=True)
    out = s.get_emoji("😀")  # no explicit args; env says off
    im = Image.open(out)  # type: ignore[arg-type]
    assert im.size == (64, 64)
