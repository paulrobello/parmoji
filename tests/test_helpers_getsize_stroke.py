"""Tests for stroke_width accounting in helpers.getsize / Parmoji.getsize.

Audit Low item: getsize previously ignored stroke_width, so stroked text
measured NARROWER than it rendered (Parmoji.text forwards stroke_width to
Pillow's ImageDraw.text). These tests pin the corrected behavior: a stroked
text run measures 2*stroke_width wider per line (once per run, matching how
Pillow renders stroke), emoji-only lines are unaffected, and the default
stroke_width=0 is unchanged.
"""

from __future__ import annotations

from PIL import Image, ImageFont

from parmoji import Parmoji
from parmoji.helpers import getsize as helpers_getsize
from parmoji.helpers import to_nodes


def _font() -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    return ImageFont.load_default()


def test_getsize_stroke_width_increases_text_width():
    # Core audit assertion: stroked text must measure wider than non-stroked.
    font = _font()
    plain = helpers_getsize("Hello", font=font)
    stroked = helpers_getsize("Hello", font=font, stroke_width=5)
    assert stroked[0] > plain[0], f"stroked {stroked[0]} should exceed plain {plain[0]}"
    assert stroked[1] == plain[1], "stroke_width must not change height"


def test_getsize_stroke_width_delta_is_exactly_2x_per_line():
    # Pillow renders stroke_width pixels of outline on each side of a glyph
    # run, so the total horizontal extra is 2*stroke_width once per line
    # (verified against ImageDraw.textbbox(..., stroke_width=N)).
    font = _font()
    plain_w = helpers_getsize("Hello", font=font)[0]
    for sw in (1, 2, 3, 5, 10):
        stroked_w = helpers_getsize("Hello", font=font, stroke_width=sw)[0]
        assert stroked_w - plain_w == 2 * sw, f"sw={sw}: delta {stroked_w - plain_w} != {2 * sw}"


def test_getsize_stroke_width_zero_is_default_and_backward_compatible():
    # Passing stroke_width=0 must match not passing it at all (historical
    # behavior) so existing callers are unaffected.
    font = _font()
    omitted = helpers_getsize("Hello", font=font)
    explicit_zero = helpers_getsize("Hello", font=font, stroke_width=0)
    assert omitted == explicit_zero


def test_getsize_stroke_applied_once_per_line_not_per_text_segment():
    # A line with TWO text nodes separated by an emoji still renders as a single
    # Pillow run, so stroke must add 2*sw once — not once per text node.
    # (The parser's longest-match window is 10 chars, so leading text beyond
    # that window and trailing text become separate text nodes around the emoji.)
    font = _font()
    text = "HelloHello \U0001f600 WorldWorld"  # parses to text + emoji + text
    nodes = [n for line in to_nodes(text) for n in line]
    text_node_count = sum(1 for n in nodes if n.type.name == "text")
    assert text_node_count >= 2, f"test premise: need >=2 text nodes, got {text_node_count}"
    plain_w = helpers_getsize(text, font=font, emoji_scale_factor=1.0)[0]
    stroked_w = helpers_getsize(text, font=font, emoji_scale_factor=1.0, stroke_width=5)[0]
    assert stroked_w - plain_w == 2 * 5, (
        f"2-text-node line delta {stroked_w - plain_w} != 10 (stroke must be once per run, not per text node)"
    )


def test_getsize_stroke_does_not_affect_emoji_only_line():
    # Emoji glyphs have no stroke; an emoji-only line's width is unchanged.
    font = _font()
    emoji = "\U0001f600"
    plain_w = helpers_getsize(emoji, font=font, emoji_scale_factor=1.0)[0]
    stroked_w = helpers_getsize(emoji, font=font, emoji_scale_factor=1.0, stroke_width=5)[0]
    assert stroked_w == plain_w, f"emoji-only line changed by stroke: {stroked_w} != {plain_w}"


def test_getsize_stroke_applies_per_text_line_in_multiline():
    # Each text-bearing line gets its own 2*sw term (one run per line).
    font = _font()
    plain_w = helpers_getsize("Hello\nWorld", font=font)[0]
    stroked_w = helpers_getsize("Hello\nWorld", font=font, stroke_width=4)[0]
    assert stroked_w - plain_w == 2 * 4, (
        f"multiline delta {stroked_w - plain_w} != 8 (each text line gets one 2*sw term)"
    )


def test_parmoji_getsize_accepts_and_forwards_stroke_width():
    # Parmoji.getsize must expose the same keyword and forward it.
    img = Image.new("RGBA", (10, 10))
    with Parmoji(img, disk_cache=False) as p:
        plain = p.getsize("Hello", font=_font())
        stroked = p.getsize("Hello", font=_font(), stroke_width=6)
    assert stroked[0] - plain[0] == 2 * 6
    assert stroked[1] == plain[1]
