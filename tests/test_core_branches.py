from __future__ import annotations

from io import BytesIO

import pytest
from PIL import Image, ImageFont

from parmoji.core import Parmoji
from parmoji.source import BaseSource, TwitterEmojiSource


class _CountSrc(BaseSource):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.calls = 0
        self.calls_d = 0

    def get_emoji(self, emoji: str):
        from PIL import Image

        self.calls += 1
        im = Image.new("RGBA", (6, 6), (255, 255, 255, 255))
        b = BytesIO()
        im.save(b, format="PNG")
        b.seek(0)
        return b

    def get_discord_emoji(self, emoji_id: int):
        from PIL import Image

        self.calls_d += 1
        im = Image.new("RGBA", (6, 6), (0, 0, 255, 255))
        b = BytesIO()
        im.save(b, format="PNG")
        b.seek(0)
        return b


@pytest.mark.parmoji
def test_textlength_zero_space_handled(monkeypatch):
    img = Image.new("RGBA", (120, 60), (0, 0, 0, 0))
    src = _CountSrc(disk_cache=False)
    font = ImageFont.load_default()
    with Parmoji(img, source=src, cache=True) as p:
        # Return 0 for a single space to hit the guard path
        orig_textlength = p.draw.textlength  # type: ignore[assignment]

        def _tl(s, *a, **k):  # noqa: ANN001
            if s == " ":
                return 0
            return orig_textlength(s, *a, **k)

        monkeypatch.setattr(p.draw, "textlength", _tl, raising=False)  # type: ignore[arg-type]
        p.text((2, 2), "😀", font=font)
    # Ensure we actually fetched the emoji and pasted it
    assert src.calls >= 1


@pytest.mark.parmoji
def test_close_clears_caches_after_use():
    img = Image.new("RGBA", (64, 32), (0, 0, 0, 0))
    src = _CountSrc(disk_cache=False)
    p = Parmoji(img, source=src, cache=True)
    # Fill both caches
    assert p._get_emoji("😀") is not None
    assert p._get_discord_emoji(1) is not None
    assert len(p._emoji_cache) >= 1 and len(p._discord_emoji_cache) >= 1
    p.close()
    # Caches recreated empty
    assert len(p._emoji_cache) == 0 and len(p._discord_emoji_cache) == 0


@pytest.mark.parmoji
def test_httpbased_open_reinit():
    img = Image.new("RGBA", (10, 10), (0, 0, 0, 0))
    p = Parmoji(img, source=TwitterEmojiSource, cache=False)
    p.close()
    p.open()  # should not raise and should reinit requests session when available
    p.close()
