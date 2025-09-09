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
import re
import unicodedata
from enum import Enum
from typing import TYPE_CHECKING, Final, List, NamedTuple, Optional, Tuple

import emoji
import PIL
from PIL import Image, ImageDraw, ImageFont

if TYPE_CHECKING:
    from .core import FontT

# Check PIL version once at module level
PIL_VERSION = tuple(int(part) for part in PIL.__version__.split("."))
HAS_GETLENGTH = PIL_VERSION >= (9, 2, 0)

# More efficient emoji detection using a set for O(1) lookup
EMOJI_SET: set[str] = set()
for emj, data in emoji.EMOJI_DATA.items():
    if "en" in data and data["status"] <= emoji.STATUS["fully_qualified"]:
        EMOJI_SET.add(emj)

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

    # Fast-path: check our known emoji set
    if char in EMOJI_SET:
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


def find_emojis_in_text(text: str) -> List[Tuple[int, int, str]]:
    """Find all emojis in text efficiently.

    Returns list of (start_index, end_index, emoji) tuples.
    """
    emojis = []
    i = 0
    while i < len(text):
        # Check for Discord emoji first (faster regex)
        match = DISCORD_EMOJI_PATTERN.match(text, i)
        if match:
            emojis.append((match.start(), match.end(), match.group()))
            i = match.end()
            continue

        # Check for Unicode emoji
        # Try to match the longest possible emoji sequence
        for length in range(min(10, len(text) - i), 0, -1):
            candidate = text[i : i + length]
            if is_emoji(candidate):
                emojis.append((i, i + length, candidate))
                i += length
                break
        else:
            i += 1

    return emojis


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
    """

    type: NodeType
    content: str

    def __repr__(self) -> str:
        return f"<Node type={self.type.name!r} content={self.content!r}>"


def _parse_line(line: str, /) -> List[Node]:
    """Parse a line of text into nodes, efficiently detecting emojis."""
    nodes = []

    # Find all emojis in the line
    emojis = find_emojis_in_text(line)

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
            # Extract ID from Discord emoji format
            emoji_id = emoji_text.split(":")[-1][:-1]
            nodes.append(Node(NodeType.discord_emoji, emoji_id))
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
    text: str, font: Optional[FontT] = None, *, spacing: int = 4, emoji_scale_factor: float = 1
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
    """
    if font is None:
        font = ImageFont.load_default()

    x, y = 0, 0
    nodes = to_nodes(text)

    for line in nodes:
        this_x = 0
        for node in line:
            content = node.content

            if node.type is not NodeType.text:
                width = int(emoji_scale_factor * getattr(font, "size", 16))  # type: ignore[attr-defined]
            elif HAS_GETLENGTH:
                width = int(font.getlength(content))  # type: ignore[call-arg]
            else:
                # Approximate width using textlength for compatibility with type stubs
                tmp_img = Image.new("RGB", (10, 10))
                tmp_draw = ImageDraw.Draw(tmp_img)
                width = int(tmp_draw.textlength(content, font=font))

            this_x += width

        y += spacing + int(getattr(font, "size", 16))  # type: ignore[attr-defined]

        x = max(x, this_x)

    return x, y - spacing
