from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image, ImageFont

from parmoji import Parmoji


def _non_empty_bbox(im: Image.Image):
    # Returns bounding box of non-transparent pixels or None
    return im.getbbox()


@pytest.mark.parmoji
def test_emoji_renders_with_alpha_and_reasonable_alignment(stub_emoji_source, tmp_path: Path):
    # QA-004: use the opt-in stub source (real PNG bytes) instead of
    # LocalFontSource, which may render a blank image on CI sandboxes without
    # color-emoji fonts. The stub flows through the real paste path.
    img = Image.new("RGBA", (160, 100), (0, 0, 0, 0))
    font = ImageFont.load_default()

    with Parmoji(img, source=stub_emoji_source, disk_cache=False) as p:
        p.text((10, 10), "😀", font=font)

    # The image should now contain non-transparent pixels where the emoji was drawn
    bbox = _non_empty_bbox(img)
    assert bbox is not None
    x0, y0, x1, y1 = bbox
    # Sanity: something was drawn near the origin and within image bounds
    assert 0 <= x0 < x1 <= img.width
    assert 0 <= y0 < y1 <= img.height


@pytest.mark.parmoji
def test_scaling_factor_changes_emoji_size(stub_emoji_source, tmp_path: Path):
    # QA-004: stub source makes the processed-cache assertions hermetic and
    # honest (real resized assets) rather than depending on LocalFontSource.
    img = Image.new("RGBA", (240, 120), (0, 0, 0, 0))
    font = ImageFont.load_default()

    with Parmoji(img, source=stub_emoji_source, disk_cache=False) as p:
        # First at scale 1.0
        p.text((10, 10), "😀", font=font, emoji_scale_factor=1.0)
        # Then at scale 2.0, offset on x so we don't overlap
        p.text((120, 10), "😀", font=font, emoji_scale_factor=2.0)

        # Access processed cache (keyed by content and scale)
        im1 = p._processed_image_cache.get("😀_1.0")
        im2 = p._processed_image_cache.get("😀_2.0")

    # Both sizes should exist and the latter should be about double width
    assert im1 is not None and im2 is not None
    assert im1.width > 0 and im2.width > 0
    ratio = im2.width / im1.width
    assert 1.7 <= ratio <= 2.3, f"expected ~2x width, got ratio={ratio:.2f} (w1={im1.width}, w2={im2.width})"
