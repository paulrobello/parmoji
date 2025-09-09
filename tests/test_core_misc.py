from __future__ import annotations

from io import BytesIO

import pytest
from PIL import Image, ImageFont

from parmoji.core import LRUCacheDict, Parmoji
from parmoji.source import BaseSource


class _CountingSource(BaseSource):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.calls_emoji = 0
        self.calls_discord = 0

    def get_emoji(self, emoji: str):
        from PIL import Image

        self.calls_emoji += 1
        # Produce a tiny valid PNG
        im = Image.new("RGBA", (8, 8), (255, 0, 0, 255))
        buf = BytesIO()
        im.save(buf, format="PNG")
        buf.seek(0)
        return buf

    def get_discord_emoji(self, emoji_id: int):
        from PIL import Image

        self.calls_discord += 1
        im = Image.new("RGBA", (8, 8), (0, 255, 0, 255))
        buf = BytesIO()
        im.save(buf, format="PNG")
        buf.seek(0)
        return buf


@pytest.mark.parmoji
def test_parmoji_open_close_cycle_and_errors():
    img = Image.new("RGBA", (64, 32), (0, 0, 0, 0))
    src = _CountingSource(disk_cache=False)

    p = Parmoji(img, source=src, cache=True)

    # Double-open should error
    with pytest.raises(ValueError):
        p.open()

    # Normal close then reopen
    p.close()
    p.open()

    # Second close should error
    p.close()
    with pytest.raises(ValueError):
        p.close()


@pytest.mark.parmoji
def test_lru_eviction_closes_streams():
    lru = LRUCacheDict(maxsize=1)
    a = BytesIO(b"a")
    b = BytesIO(b"b")
    lru["a"] = a
    assert not a.closed
    lru["b"] = b  # evicts "a" and closes it
    assert a.closed
    assert lru.get("b") is b


@pytest.mark.parmoji
def test_get_emoji_and_discord_cache_copy_semantics():
    img = Image.new("RGBA", (64, 32), (0, 0, 0, 0))
    src = _CountingSource(disk_cache=False)
    p = Parmoji(img, source=src, cache=True)

    # Emoji cache
    s1 = p._get_emoji("😀")
    s2 = p._get_emoji("😀")
    assert s1 is not None and s2 is not None
    # Underlying source only called once
    assert src.calls_emoji == 1
    # Returned streams are independent
    s1.seek(0)
    s2.seek(0)
    assert s1 is not s2

    # Discord cache
    d1 = p._get_discord_emoji(123)
    d2 = p._get_discord_emoji(123)
    assert d1 is not None and d2 is not None
    assert src.calls_discord == 1


@pytest.mark.parmoji
def test_validate_anchor_and_direction_errors():
    # wrong length
    with pytest.raises(ValueError):
        Parmoji._validate_anchor_and_direction("left", None, "text")
    # top/bottom anchor with multiline
    with pytest.raises(ValueError):
        Parmoji._validate_anchor_and_direction("lt", None, "a\nb")
    # ttb direction with multiline
    with pytest.raises(ValueError):
        Parmoji._validate_anchor_and_direction("la", "ttb", "a\nb")


@pytest.mark.parmoji
def test_aligned_x_invalid_align_raises():
    with pytest.raises(ValueError):
        Parmoji._aligned_x(10.0, "la", "bogus", 5)


@pytest.mark.parmoji
def test_aligned_x_center_and_right_values():
    # Center adjusts by half; right by full width_difference
    assert Parmoji._aligned_x(10.0, "la", "center", 8) == 14.0
    assert Parmoji._aligned_x(10.0, "la", "right", 8) == 18.0


@pytest.mark.parmoji
def test_constructor_source_type_errors():
    from PIL import Image

    img = Image.new("RGBA", (10, 10), (0, 0, 0, 0))
    # 1) source provided as a type that is not a BaseSource subclass
    with pytest.raises(TypeError):
        Parmoji(img, source=int)  # type: ignore[arg-type]
    # 2) source provided as an instance that is not a BaseSource
    with pytest.raises(TypeError):
        Parmoji(img, source=object())  # type: ignore[arg-type]


@pytest.mark.parmoji
def test_getsize_uses_default_emoji_scale_when_none():
    from PIL import Image
    from PIL import ImageFont

    img = Image.new("RGBA", (10, 10), (0, 0, 0, 0))
    font = ImageFont.load_default()
    p = Parmoji(img)
    w1, h1 = p.getsize("A😀B", font=font, spacing=2, emoji_scale_factor=None)
    assert w1 > 0 and h1 > 0


@pytest.mark.parmoji
def test_text_plain_ascii_draw_and_apply_font_offset_ink_none(monkeypatch):
    from PIL import Image
    from PIL import ImageFont

    img = Image.new("RGBA", (40, 20), (0, 0, 0, 0))
    font = ImageFont.load_default()
    with Parmoji(img, cache=False) as p:
        # Make ctx.ink None without impacting PIL's own draw.text inking
        from parmoji import core

        monkeypatch.setattr(core.Parmoji, "_resolve_ink", lambda *a, **k: None)
        p.text((1, 1), "abc", font=font)


@pytest.mark.parmoji
def test_adjust_y_for_anchor_middle_and_descender():
    # middle (m) and descender (d) branches
    y = Parmoji._adjust_y_for_anchor(10.0, "lm", 3, 5.0)
    assert y == 10.0 - (3 - 1) * 5.0 / 2.0
    y2 = Parmoji._adjust_y_for_anchor(10.0, "ld", 3, 5.0)
    assert y2 == 10.0 - (3 - 1) * 5.0


@pytest.mark.parmoji
def test_text_simple_smoke_for_internal_paths():
    # Ensure text() exercises build/paste pipelines with a simple emoji
    img = Image.new("RGBA", (120, 60), (0, 0, 0, 0))
    src = _CountingSource(disk_cache=False)
    font = ImageFont.load_default()
    with Parmoji(img, source=src, cache=True) as p:
        p.text((10, 10), "Hi 😀", font=font, emoji_scale_factor=1.0)
    # Should have fetched at least one emoji
    assert src.calls_emoji >= 1
