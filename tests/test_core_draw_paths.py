from __future__ import annotations

from io import BytesIO

import pytest
from PIL import Image, ImageFont

from parmoji.core import Parmoji
from parmoji.source import BaseSource


class _Src(BaseSource):
    def get_emoji(self, emoji: str):
        from PIL import Image

        im = Image.new("RGBA", (8, 8), (255, 255, 255, 255))
        b = BytesIO()
        im.save(b, format="PNG")
        b.seek(0)
        return b

    def get_discord_emoji(self, emoji_id: int):
        from PIL import Image

        im = Image.new("RGBA", (8, 8), (255, 0, 0, 255))
        b = BytesIO()
        im.save(b, format="PNG")
        b.seek(0)
        return b


@pytest.mark.parmoji
def test_draw_block_executes_for_emoji(monkeypatch):
    img = Image.new("RGBA", (50, 20), (0, 0, 0, 0))
    font = ImageFont.load_default()
    with Parmoji(img, source=_Src(disk_cache=False), cache=False) as p:
        # Make a single space extremely narrow so placeholder emits characters
        orig = p.draw.textlength  # type: ignore[assignment]

        def _tl(s, *a, **k):  # noqa: ANN001
            if s == " ":
                return 1
            return orig(s, *a, **k)

        monkeypatch.setattr(p.draw, "textlength", _tl, raising=False)  # type: ignore[arg-type]
        p.text((5, 5), "😀", font=font)


@pytest.mark.parmoji
def test_draw_plain_text_calls_draw_text():
    img = Image.new("RGBA", (50, 20), (0, 0, 0, 0))
    font = ImageFont.load_default()
    with Parmoji(img, source=_Src(disk_cache=False), cache=False) as p:
        p.text((5, 5), "hello", font=font)


@pytest.mark.parmoji
def test_draw_block_for_discord_emoji(monkeypatch):
    img = Image.new("RGBA", (80, 30), (0, 0, 0, 0))
    font = ImageFont.load_default()
    with Parmoji(img, source=_Src(disk_cache=False), cache=False) as p:
        orig = p.draw.textlength  # type: ignore[assignment]

        def _tl(s, *a, **k):  # noqa: ANN001
            if s == " ":
                return 1
            return orig(s, *a, **k)

        monkeypatch.setattr(p.draw, "textlength", _tl, raising=False)  # type: ignore[arg-type]
        p.text((2, 2), "<:x:123456789012345678>", font=font)


@pytest.mark.parmoji
def test_processed_image_cache_hit(monkeypatch):
    img = Image.new("RGBA", (80, 30), (0, 0, 0, 0))
    font = ImageFont.load_default()
    with Parmoji(img, source=_Src(disk_cache=False), cache=False) as p:
        # Pre-insert processed asset for cache hit branch
        from PIL import Image as PILImage

        asset = PILImage.new("RGBA", (10, 10), (0, 255, 0, 255))
        p._processed_image_cache["😀_1.0"] = asset
        orig = p.draw.textlength  # type: ignore[assignment]

        def _tl(s, *a, **k):  # noqa: ANN001
            if s == " ":
                return 1
            return orig(s, *a, **k)

        monkeypatch.setattr(p.draw, "textlength", _tl, raising=False)  # type: ignore[arg-type]
        p.text((2, 2), "😀", font=font, emoji_scale_factor=1.0)


@pytest.mark.parmoji
def test_apply_font_offset_with_stroke_no_fill():
    img = Image.new("RGBA", (80, 30), (0, 0, 0, 0))
    font = ImageFont.load_default()
    with Parmoji(img, source=_Src(disk_cache=False), cache=False) as p:
        p.text((2, 2), "😀", font=font, stroke_width=1)


@pytest.mark.parmoji
def test_apply_font_offset_with_stroke_fill():
    img = Image.new("RGBA", (80, 30), (0, 0, 0, 0))
    font = ImageFont.load_default()
    with Parmoji(img, source=_Src(disk_cache=False), cache=False) as p:
        p.text((2, 2), "😀", font=font, stroke_width=1, stroke_fill=(255, 0, 0, 255))
