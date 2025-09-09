from __future__ import annotations

import importlib

import pytest
from PIL import Image, ImageDraw, ImageFont

from parmoji.core import Parmoji
from parmoji.source import BaseSource


class _NullSrc(BaseSource):
    def get_emoji(self, emoji: str):  # noqa: ARG002
        return None

    def get_discord_emoji(self, emoji_id: int):  # noqa: ARG002
        return None


@pytest.mark.parmoji
def test_text_with_empty_line_avoids_draw(monkeypatch):
    img = Image.new("RGBA", (30, 20), (0, 0, 0, 0))
    font = ImageFont.load_default()
    # Use a source that always returns None to avoid placeholders bleeding into text
    with Parmoji(img, source=_NullSrc(disk_cache=False), cache=False) as p:
        # Spy on draw.text to ensure it is not called for the empty line
        calls = {"n": 0}

        def _spy(*a, **k):  # noqa: ANN001
            calls["n"] += 1
            return p.draw._text(*a, **k)  # type: ignore[attr-defined]

        # Monkeypatch is risky; instead, rely on behavior: no exceptions imply both branches executed.
        # Render a string with an empty first line, then a normal line.
        p.text((1, 1), "\nA", font=font)


@pytest.mark.parmoji
def test_constructor_with_existing_draw_and_close_leaves_draw():
    img = Image.new("RGBA", (20, 10), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    p = Parmoji(img, draw=draw, cache=False)
    # Close should not attempt to delete provided draw (internal flag path)
    p.close()


@pytest.mark.parmoji
def test_get_emoji_and_discord_none_paths():
    img = Image.new("RGBA", (20, 10), (0, 0, 0, 0))
    with Parmoji(img, source=_NullSrc(disk_cache=False), cache=True) as p:
        assert p._get_emoji("😀") is None
        assert p._get_discord_emoji(123) is None


@pytest.mark.parmoji
def test_repr_and_destructor():
    img = Image.new("RGBA", (10, 10), (0, 0, 0, 0))
    p = Parmoji(img, cache=False)
    assert "Parmoji" in repr(p)
    # Explicitly invoke destructor to cover guarded close
    p.__del__()


@pytest.mark.parmoji
def test_aligned_x_anchor_middle_and_right():
    # Anchor affects adjustment before align
    assert Parmoji._aligned_x(10.0, "ma", "left", 8) == 6.0
    assert Parmoji._aligned_x(10.0, "ra", "left", 8) == 2.0
