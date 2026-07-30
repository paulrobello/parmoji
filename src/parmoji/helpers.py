"""Helpers for parsing text into emoji/text nodes and measuring size.

This module provides:
- Fast emoji detection using the `emoji` library with a prebuilt set fallback.
- A compact parser that splits text into Nodes per line (text/emoji/discord).
- Convenience size calculation compatible with Pillow's APIs.

The logic here is optimized for correctness and performance in the renderer,
while keeping type hints explicit for maintainability.
"""

from __future__ import annotations

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
import functools
import re
import unicodedata
from enum import Enum
from typing import TYPE_CHECKING, Any, Final, List, NamedTuple, Optional, Tuple

import emoji
import PIL
from PIL import Image, ImageDraw, ImageFont

if TYPE_CHECKING:
    from .core import FontT

# Check PIL version once at module level. Pillow prereleases/local builds carry
# segments like "12.3.0.dev0", "11.0.0rc1", or "10.2.0+local" whose dot-parts
# crash a bare int(). Pull the leading integer off each part and stop at the
# first segment without one; the result stays comparable to tuples like (9, 2, 0).


def _parse_pil_version(version: str) -> Tuple[int, ...]:
    parts: List[int] = []
    for part in version.split("."):
        m = re.match(r"\d+", part)
        if m is None:
            break
        parts.append(int(m.group()))
    return tuple(parts) if parts else (0,)


PIL_VERSION: Tuple[int, ...] = _parse_pil_version(PIL.__version__)
HAS_GETLENGTH = PIL_VERSION >= (9, 2, 0)

# QA-012: longest emoji sequence considered by _find_emojis_in_text. Kept as a
# named constant instead of the former magic 10 so the fast-path window and the
# per-length probe stay in lockstep.
_MAX_EMOJI_LEN: Final[int] = 10


@functools.lru_cache(maxsize=1)
def _build_emoji_set() -> frozenset[str]:
    # QA-014: built lazily on first use (via is_emoji or a read of EMOJI_SET)
    # and cached. Formerly this iterated all ~3,700 emoji.EMOJI_DATA entries at
    # import time, so every ``import parmoji`` paid the cost before any
    # function ran. A frozenset is returned: nothing mutates it.
    return frozenset(
        emj
        for emj, data in emoji.EMOJI_DATA.items()
        if "en" in data and data["status"] <= emoji.STATUS["fully_qualified"]
    )


def __getattr__(name: str) -> Any:
    # QA-014: PEP 562 lazy module attribute. ``EMOJI_SET`` is exposed exactly
    # as before (tests read ``helpers.EMOJI_SET``), but the one-time build runs
    # on first access rather than at import.
    if name == "EMOJI_SET":
        return _build_emoji_set()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# Discord emoji regex - this is small enough to be efficient
_DISCORD_EMOJI_REGEX = r"<a?:[a-zA-Z0-9_]{1,32}:[0-9]{17,22}>"
DISCORD_EMOJI_PATTERN: Final[re.Pattern[str]] = re.compile(_DISCORD_EMOJI_REGEX)

__all__ = ("DISCORD_EMOJI_PATTERN", "is_emoji", "Node", "NodeType", "to_nodes", "getsize")


def is_emoji(char: str) -> bool:
    """Check if a character or string is an emoji.

    This is much faster than regex matching against thousands of patterns.
    Uses set lookup (O(1)) and Unicode category checks as fallback.
    """
    # Prefer library signal when available (handles VS-16/ZWJ robustly)
    try:
        if getattr(emoji, "emoji_count", None) and emoji.emoji_count(char) > 0:  # type: ignore[attr-defined]
            return True
    except Exception:
        pass

    # Fast-path: check our known emoji set (QA-014: lazily built, cached)
    if char in _build_emoji_set():
        return True

    # Check if it might be a multi-character emoji sequence
    if len(char) > 1 and ("\u200d" in char or "\ufe0f" in char):
        # Could be a complex emoji sequence; if not in set, accept as emoji
        # to avoid false negatives on newer sequences.
        return True

    # Fallback to Unicode category check for single characters
    if len(char) == 1:
        category = unicodedata.category(char)
        # So = Symbol, other; Sk = Symbol, modifier
        # These categories often contain emoji
        return category in ("So", "Sk")

    return False


def _find_emojis_in_text(text: str) -> List[Tuple[int, int, str]]:
    """Find all emojis in text efficiently.

    Returns list of (start_index, end_index, emoji) tuples.
    """
    emojis: List[Tuple[int, int, str]] = []
    i = 0
    n = len(text)
    while i < n:
        # Check for Discord emoji first (faster regex)
        match = DISCORD_EMOJI_PATTERN.match(text, i)
        if match:
            emojis.append((match.start(), match.end(), match.group()))
            i = match.end()
            continue

        # QA-012: ASCII fast-path. is_emoji() would otherwise probe up to
        # _MAX_EMOJI_LEN candidate lengths at this position, but a window with
        # no non-ASCII codepoint can never be an emoji — no ASCII char is in
        # the emoji set, a So/Sk symbol, or part of a ZWJ / VS-16 sequence, and
        # emoji_count() only returns >0 when an actual emoji codepoint is
        # present. When the window is entirely ASCII the probe is skipped
        # entirely, which makes plain-text runs O(N) instead of O(N * 10) while
        # preserving exact emoji boundaries (the non-ASCII case still runs the
        # full longest-match probe below).
        if text[i : i + _MAX_EMOJI_LEN].isascii():
            i += 1
            continue

        # Check for Unicode emoji
        # Try to match the longest possible emoji sequence
        for length in range(min(_MAX_EMOJI_LEN, n - i), 0, -1):
            candidate = text[i : i + length]
            if is_emoji(candidate):
                emojis.append((i, i + length, candidate))
                i += length
                break
        else:
            i += 1

    return emojis


def _measure_text_width(
    text: str,
    font: FontT,
    *,
    draw: Optional[ImageDraw.ImageDraw] = None,
    direction: Optional[str] = None,
    language: Optional[str] = None,
) -> int:
    # Shared text-width measurement (QA-Low dedup). Previously the same
    # HAS_GETLENGTH-vs-textlength logic was inlined in helpers.getsize and
    # Parmoji._measure_text_width; both now call this.
    if HAS_GETLENGTH:
        return int(font.getlength(text, direction=direction, features=None, language=language))  # type: ignore[call-arg]
    if draw is None:
        draw = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    return int(draw.textlength(text, font=font, direction=direction, features=None, language=language))


class NodeType(Enum):
    """|enum|

    Represents the type of a :class:`~.Node`.

    Attributes
    ----------
    text
        This node is a raw text node.
    emoji
        This node is a unicode emoji.
    discord_emoji
        This node is a Discord emoji.
    """

    text = 0
    emoji = 1
    discord_emoji = 2


class Node(NamedTuple):
    """Represents a parsed node inside of a string.

    Attributes
    ----------
    type: :class:`~.NodeType`
        The type of this node.
    content: str
        The contents of this node.
    animated: bool
        For Discord custom emoji nodes, whether the source tag was the
        animated form (``<a:name:id>``). Always ``False`` for text and
        Unicode-emoji nodes. Carried through so the source can request the
        GIF variant (ARC-002).
    """

    type: NodeType
    content: str
    animated: bool = False

    def __repr__(self) -> str:
        return f"<Node type={self.type.name!r} content={self.content!r} animated={self.animated!r}>"


def _parse_line(line: str, /) -> List[Node]:
    """Parse a line of text into nodes, efficiently detecting emojis."""
    nodes = []

    # Find all emojis in the line
    emojis = _find_emojis_in_text(line)

    if not emojis:
        # No emojis, entire line is text
        if line:
            nodes.append(Node(NodeType.text, line))
        return nodes

    # Build nodes, alternating between text and emoji
    last_end = 0
    for start, end, emoji_text in emojis:
        # Add text before emoji if any
        if start > last_end:
            nodes.append(Node(NodeType.text, line[last_end:start]))

        # Add emoji node
        if emoji_text.startswith("<"):  # Discord emoji
            # Discord custom emoji format: <:name:id> (static, PNG) or
            # <a:name:id> (animated, GIF). ARC-002: preserve the animated
            # flag so the source can request the GIF variant.
            animated = emoji_text.startswith("<a:")
            emoji_id = emoji_text.split(":")[-1][:-1]
            nodes.append(Node(NodeType.discord_emoji, emoji_id, animated=animated))
        else:
            nodes.append(Node(NodeType.emoji, emoji_text))

        last_end = end

    # Add remaining text after last emoji
    if last_end < len(line):
        nodes.append(Node(NodeType.text, line[last_end:]))

    return nodes


def to_nodes(text: str, /) -> List[List[Node]]:
    """Parses a string of text into :class:`~.Node`s.

    This method will return a nested list, each element of the list
    being a list of :class:`~.Node`s and representing a line in the string.

    The string ``'Hello\nworld'`` would return something similar to
    ``[[Node('Hello')], [Node('world')]]``.

    Parameters
    ----------
    text: str
        The text to parse into nodes.

    Returns
    -------
    List[List[:class:`~.Node`]]
    """
    return [_parse_line(line) for line in text.splitlines()]


def getsize(
    text: str,
    font: Optional[FontT] = None,
    *,
    spacing: int = 4,
    emoji_scale_factor: float = 1,
    stroke_width: int = 0,
) -> Tuple[int, int]:
    """Return the width and height of the text when rendered.
    This method supports multiline text.

    Parameters
    ----------
    text: str
        The text to use.
    font
        The font of the text.
    spacing: int
        The spacing between lines, in pixels.
        Defaults to `4`.
    emoji_scale_factor: float
        The rescaling factor for emojis.
        Defaults to `1`.
    stroke_width: int
        The text stroke width, in pixels, matching the ``stroke_width`` argument
        forwarded to Pillow's ``ImageDraw.text`` by :meth:`Parmoji.text`. When
        greater than zero, the width accounts for the stroke outline Pillow
        renders around each text run. Emoji glyphs have no stroke and are
        unaffected. Defaults to `0` (no stroke — historical behavior).
    """
    if font is None:
        font = ImageFont.load_default()

    x, y = 0, 0
    nodes = to_nodes(text)

    for line in nodes:
        this_x = 0
        line_has_text = False
        for node in line:
            content = node.content

            if node.type is not NodeType.text:
                width = int(emoji_scale_factor * getattr(font, "size", 16))  # type: ignore[attr-defined]
            else:
                line_has_text = True
                width = _measure_text_width(content, font)

            this_x += width

        # Stroke renders a `stroke_width`-pixel outline on each side of the
        # glyph run. Pillow draws each line as a single run (one
        # ImageDraw.text call), so the total horizontal extra is
        # 2*stroke_width once per line containing text — not per text segment
        # and not on emoji. Verified against textbbox(..., stroke_width=N)
        # which returns exactly advance_width + 2*N. Emoji have no stroke, so
        # lines with no text node are unaffected.
        if stroke_width > 0 and line_has_text:
            this_x += 2 * stroke_width

        y += spacing + int(getattr(font, "size", 16))  # type: ignore[attr-defined]

        x = max(x, this_x)

    return x, y - spacing
