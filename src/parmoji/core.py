"""Pillow-based emoji renderer for mixing text and emoji.

`Parmoji` draws text that can contain both Unicode emoji and Discord custom
emoji onto a Pillow image. It uses a pluggable `BaseSource` to fetch emoji
images (HTTP CDN, local font, or offline cache), and mirrors PIL's text
placement semantics including anchors and alignment.
"""

from __future__ import annotations

import logging
import math
import threading
from collections import OrderedDict
from contextlib import suppress
from dataclasses import dataclass
from io import BytesIO
from typing import TYPE_CHECKING, Any, Dict, List, Optional, SupportsInt, Tuple, Type, TypeVar, Union, cast

import PIL
from PIL import Image, ImageDraw, ImageFont

try:
    from requests import Session  # type: ignore
except Exception:  # pragma: no cover - requests optional at runtime
    Session = None  # type: ignore[assignment]

from .helpers import NodeType, getsize, to_nodes
from .source import BaseSource, HTTPBasedSource, Twemoji, _has_requests

logger = logging.getLogger(__name__)

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportAttributeAccessIssue=false

# Check PIL version once at module level
PIL_VERSION = tuple(int(part) for part in PIL.__version__.split("."))
HAS_GETLENGTH = PIL_VERSION >= (9, 2, 0)

# Check for Pillow 10+ resampling with safe fallback
try:
    from PIL.Image import Resampling as _Resampling  # type: ignore[attr-defined]

    LANCZOS: Any = _Resampling.LANCZOS
except Exception:
    # Fallback using getattr to satisfy type stubs
    LANCZOS: Any = getattr(Image, "LANCZOS", getattr(Image, "BICUBIC", 1))

if TYPE_CHECKING:
    from io import BytesIO

    FontT = Union[ImageFont.ImageFont, ImageFont.FreeTypeFont, ImageFont.TransposedFont]
    ColorBaseT = Union[int, Tuple[int, int, int], Tuple[int, int, int, int], str]
else:
    # Runtime-only aliases for readability
    FontT = Any  # type: ignore[assignment]
    ColorBaseT = Any  # type: ignore[assignment]

ColorT = Optional[ColorBaseT]


P = TypeVar("P", bound="Parmoji")

__all__ = ("Parmoji",)

# Module-level constants for small magic values
ANCHOR_LEN: int = 2


class LRUCacheDict(OrderedDict[Any, Any]):
    """Simple LRU cache implementation using OrderedDict.

    Note: Uses Any typing to avoid issues with external stubs and keep runtime behavior intact.
    """

    def __init__(self, maxsize: int = 1000) -> None:
        super().__init__()
        self.maxsize: int = maxsize
        self._lock: threading.Lock = threading.Lock()

    def __setitem__(self, key: Any, value: Any) -> None:  # type: ignore[override]
        with self._lock:
            if key in self:
                # Move to end (most recently used)
                self.move_to_end(key)
            super().__setitem__(key, value)
            if len(self) > self.maxsize:
                # Remove least recently used
                oldest = next(iter(self))
                # Close BytesIO if it exists
                val = super().__getitem__(oldest)
                if hasattr(val, "close"):
                    with suppress(Exception):
                        val.close()  # type: ignore[call-arg]
                del self[oldest]

    def __getitem__(self, key: Any) -> Any:  # type: ignore[override]
        with self._lock:
            value = super().__getitem__(key)
            # Move to end (most recently used)
            self.move_to_end(key)
            return value

    def get(self, key: Any, default: Any = None) -> Any:  # type: ignore[override]
        # Avoid calling __getitem__ while holding the lock (would deadlock)
        with self._lock:
            if key in self:
                value = super().__getitem__(key)  # type: ignore[misc]
                # Move to end (most recently used)
                super().move_to_end(key)
                return value
            return default


class Parmoji:
    """The main emoji rendering interface.

    .. note::
        This should be used in a context manager.

    Parameters
    ----------
    image: :class:`PIL.Image.Image`
        The Pillow image to render on.
    source: Union[:class:`~.BaseSource`, Type[:class:`~.BaseSource`]]
        The emoji image source to use.
        This defaults to :class:`~.TwitterEmojiSource`.
    cache: bool
        Whether or not to cache emojis given from source.
        Enabling this is recommended and by default.
    cache_size: int
        Maximum number of cached emojis (default 1000).
    draw: :class:`PIL.ImageDraw.ImageDraw`
        The drawing instance to use. If left unfilled,
        a new drawing instance will be created.
    render_discord_emoji: bool
        Whether or not to render Discord emoji. Defaults to `True`
    emoji_scale_factor: float
        The default rescaling factor for emojis. Defaults to `1`
    emoji_position_offset: Tuple[int, int]
        A 2-tuple representing the x and y offset for emojis when rendering,
        respectively. Defaults to `(0, 0)`
    disk_cache: bool
        Whether or not to permanently cache cdn-fetched emojis to disk,
        defaults to `False` but can greatly improve speed in certain cases.
    """

    def __init__(  # noqa: PLR0913 - public API mirrors Pillow + extras
        self,
        image: Image.Image,
        *,
        source: Union[BaseSource, Type[BaseSource]] = Twemoji,
        cache: bool = True,
        cache_size: int = 1000,
        draw: Optional[ImageDraw.ImageDraw] = None,
        render_discord_emoji: bool = True,
        emoji_scale_factor: float = 1.0,
        emoji_position_offset: Tuple[int, int] = (0, 0),
        disk_cache: bool = False,
    ) -> None:
        self.image: Image.Image = image
        self.draw: Optional[ImageDraw.ImageDraw] = draw

        if isinstance(source, type):
            if not issubclass(source, BaseSource):
                raise TypeError(f"source must inherit from BaseSource, not {source}.")

            source = source(disk_cache=disk_cache)

        elif not isinstance(source, BaseSource):
            raise TypeError(f"source must inherit from BaseSource, not {source.__class__}.")

        self.source: BaseSource = source

        self._cache: bool = cache
        self._cache_size: int = cache_size
        self._closed: bool = False
        self._new_draw: bool = False

        self._render_discord_emoji: bool = render_discord_emoji
        self._default_emoji_scale_factor: float = emoji_scale_factor
        self._default_emoji_position_offset: Tuple[int, int] = emoji_position_offset

        # Use LRU cache with size limit to prevent memory leaks
        self._emoji_cache: LRUCacheDict = LRUCacheDict(maxsize=cache_size)
        self._discord_emoji_cache: LRUCacheDict = LRUCacheDict(maxsize=cache_size // 2)

        # Cache for processed images to avoid double processing
        self._processed_image_cache: Dict[str, Image.Image] = {}
        self._cache_lock = threading.Lock()

        self._create_draw()

    def open(self) -> None:
        """Re-opens this renderer if it has been closed.
        This should rarely be called.

        Raises
        ------
        ValueError
            The renderer is already open.
        """
        if not self._closed:
            raise ValueError("Renderer is already open.")

        if _has_requests and isinstance(self.source, HTTPBasedSource) and Session is not None:
            self.source._requests_session = Session()  # type: ignore[misc]

        self._create_draw()
        self._closed = False

    def close(self) -> None:
        """Safely closes this renderer.

        .. note::
            If you are using a context manager, this should not be called.

        Raises
        ------
        ValueError
            The renderer has already been closed.
        """
        if self._closed:
            raise ValueError("Renderer has already been closed.")

        if self._new_draw:
            del self.draw
            self.draw = None

        if isinstance(self.source, HTTPBasedSource):
            # Use the source's close method which handles httpx/requests properly
            self.source.close()

        if self._cache:
            for stream in self._emoji_cache.values():
                stream.close()

            for stream in self._discord_emoji_cache.values():
                stream.close()

            self._emoji_cache = LRUCacheDict(maxsize=self._cache_size)
            self._discord_emoji_cache = LRUCacheDict(maxsize=max(1, self._cache_size // 2))

        self._closed = True

    def _create_draw(self) -> None:
        if self.draw is None:
            self._new_draw = True
            self.draw = ImageDraw.Draw(self.image)

    def _get_emoji(self, emoji: str, /) -> Optional[BytesIO]:
        if self._cache:
            cached = self._emoji_cache.get(emoji)
            if cached:
                # Create a new BytesIO copy to avoid thread issues
                with self._cache_lock:
                    cached.seek(0)
                    return BytesIO(cached.read())

        stream = self.source.get_emoji(emoji)
        if stream:
            if self._cache:
                # Store a copy in cache
                stream.seek(0)
                cache_copy = BytesIO(stream.read())
                self._emoji_cache[emoji] = cache_copy
                stream.seek(0)
            return stream
        return None

    def _get_discord_emoji(self, emoji_id: SupportsInt, /) -> Optional[BytesIO]:
        emoji_id = int(emoji_id)

        if self._cache:
            cached = self._discord_emoji_cache.get(emoji_id)
            if cached:
                # Create a new BytesIO copy to avoid thread issues
                with self._cache_lock:
                    cached.seek(0)
                    return BytesIO(cached.read())

        stream = self.source.get_discord_emoji(emoji_id)
        if stream:
            if self._cache:
                # Store a copy in cache
                stream.seek(0)
                cache_copy = BytesIO(stream.read())
                self._discord_emoji_cache[emoji_id] = cache_copy
                stream.seek(0)
            return stream
        return None

    # This helper mirrors Pillow's removed multiline spacing logic (Pillow ≥11.2).
    # Implementation derived from Pillow; see license:
    # https://github.com/python-pillow/Pillow/blob/main/LICENSE
    def _multiline_spacing(
        self,
        font: ImageFont.ImageFont | ImageFont.FreeTypeFont | ImageFont.TransposedFont,
        spacing: float,
        stroke_width: float,
    ) -> float:
        assert self.draw is not None
        return self.draw.textbbox((0, 0), "A", font, stroke_width=stroke_width)[3] + stroke_width + spacing

    def getsize(
        self, text: str, font: Optional[FontT] = None, *, spacing: int = 4, emoji_scale_factor: Optional[float] = None
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
            Defaults to the factor given in the class constructor, or `1`.
        """
        if emoji_scale_factor is None:
            emoji_scale_factor = self._default_emoji_scale_factor

        return getsize(text, font, spacing=spacing, emoji_scale_factor=emoji_scale_factor)

    def text(  # noqa: PLR0913 - public API mirrors Pillow's ImageDraw.text
        self,
        xy: Tuple[int, int],
        text: str,
        fill: ColorT = None,
        font: Optional[FontT] = None,
        anchor: Optional[str] = None,
        spacing: int = 4,
        node_spacing: int = 0,
        align: str = "left",
        direction: Optional[str] = None,
        features: Optional[List[str]] = None,
        language: Optional[str] = None,
        stroke_width: int = 0,
        stroke_fill: ColorT = None,
        embedded_color: bool = False,
        *args,
        emoji_scale_factor: Optional[float] = None,
        emoji_position_offset: Optional[Tuple[int, int]] = None,
        **kwargs,
    ) -> None:
        """Draws the string at the given position, with emoji rendering support.
        This method supports multiline text.

        .. note::
            Some parameters have not been implemented yet.

        .. note::
            The signature of this function is a superset of the signature of Pillow's `ImageDraw.text`.

        .. note::
            Not all parameters are listed here.

        Parameters
        ----------
        xy: Tuple[int, int]
            The position to render the text at.
        text: str
            The text to render.
        fill
            The fill color of the text.
        font
            The font to render the text with.
        spacing: int
            How many pixels there should be between lines. Defaults to `4`
        node_spacing: int
            How many pixels there should be between nodes (text/unicode_emojis/custom_emojis). Defaults to `0`
        emoji_scale_factor: float
            The rescaling factor for emojis. This can be used for fine adjustments.
            Defaults to the factor given in the class constructor, or `1`.
        emoji_position_offset: Tuple[int, int]
            The emoji position offset for emojis. This can be used for fine adjustments.
            Defaults to the offset given in the class constructor, or `(0, 0)`.
        """

        # Prepare font/draw/emoji defaults and validate anchor/direction
        font, emoji_scale_factor, emoji_position_offset, draw = self._prepare_text_params(
            font, emoji_scale_factor, emoji_position_offset
        )
        anchor = self._validate_anchor_and_direction(anchor, direction, text)

        # Bundle rendering parameters into a context object to minimize arg counts
        ctx = _RenderCtx(
            draw=draw,
            font=font,
            fill=fill,
            anchor=anchor,
            spacing=spacing,
            node_spacing=node_spacing,
            align=align,
            direction=direction,
            features=features,
            language=language,
            stroke_width=stroke_width,
            stroke_fill=stroke_fill,
            embedded_color=embedded_color,
            args=args,
            kwargs=kwargs,
            emoji_scale_factor=float(emoji_scale_factor),
            emoji_position_offset=emoji_position_offset,
            mode=(draw.fontmode if not (stroke_width == 0 and embedded_color) else "RGBA"),
            ink=self._resolve_ink(draw, fill),
        )

        # Layout: split into nodes and precompute per-line placeholders/widths
        nodes = to_nodes(text)
        line_spacing = self._multiline_spacing(font, spacing, stroke_width)
        nodes_line_to_print, widths, max_width, streams = self._build_lines(nodes=nodes, ctx=ctx)

        # Anchor-adjust initial y for multi-line text
        x, y = xy
        original_x = x
        y = self._adjust_y_for_anchor(y, anchor, len(nodes), line_spacing)

        # Draw each line once; then paste emoji and advance
        for node_id, line in enumerate(nodes):
            x_line = self._aligned_x(original_x, anchor, align, max_width - widths[node_id])

            # Draw the plain-text line (with emoji placeholders)
            line_text = nodes_line_to_print[node_id]
            if line_text:
                ctx.draw.text(
                    (x_line, y),
                    line_text,
                    *ctx.args,
                    fill=ctx.fill,
                    font=ctx.font,
                    anchor=ctx.anchor,
                    spacing=ctx.spacing,
                    align=ctx.align,
                    direction=ctx.direction,
                    features=ctx.features,
                    language=ctx.language,
                    stroke_width=ctx.stroke_width,
                    stroke_fill=ctx.stroke_fill,
                    embedded_color=ctx.embedded_color,
                    **ctx.kwargs,
                )

            # Compute PIL text offset similar to ImageDraw.text internals
            x_line, line_y = self._apply_font_offset(line_text, x_line, y, ctx)

            # Paste emoji and advance x across nodes
            x_line = self._paste_emoji_for_line(
                line=line,
                streams=streams.get(node_id, {}),
                x_start=x_line,
                y_start=line_y,
                ctx=ctx,
            )

            y += line_spacing

    def __enter__(self: P) -> P:
        return self

    def __exit__(self, *_) -> None:
        self.close()

    def __del__(self) -> None:
        """Cleanup resources if not properly closed."""
        try:
            if not self._closed:
                self.close()
        except Exception:
            pass

    def __repr__(self) -> str:
        return f"<Parmoji source={self.source} cache={self._cache}>"

    # -----------------
    # Private helpers
    # -----------------

    def _prepare_text_params(
        self,
        font: Optional[FontT],
        emoji_scale_factor: Optional[float],
        emoji_position_offset: Optional[Tuple[int, int]],
    ) -> Tuple[FontT, float, Tuple[int, int], ImageDraw.ImageDraw]:
        if emoji_scale_factor is None:
            emoji_scale_factor = self._default_emoji_scale_factor
        if emoji_position_offset is None:
            emoji_position_offset = self._default_emoji_position_offset
        if font is None:
            font = ImageFont.load_default()
        if self.draw is None:
            self._create_draw()
        assert self.draw is not None
        return font, float(emoji_scale_factor), emoji_position_offset, self.draw

    @staticmethod
    def _validate_anchor_and_direction(anchor: Optional[str], direction: Optional[str], text: str) -> str:
        if anchor is None:
            anchor = "la"
        elif len(anchor) != ANCHOR_LEN:
            msg = "anchor must be a 2 character string"
            raise ValueError(msg)
        elif anchor[1] in "tb" and "\n" in text:
            msg = "anchor not supported for multiline text"
            raise ValueError(msg)

        # not using ImageDraw.multiline_text; mirror its restriction for ttb
        if direction == "ttb" and "\n" in text:
            msg = "ttb direction is unsupported for multiline text"
            raise ValueError(msg)
        return anchor

    @staticmethod
    def _resolve_ink(draw: ImageDraw.ImageDraw, fill: ColorT) -> Any:
        # Access private _getink like Pillow's ImageDraw.text does to compute offsets
        ink, f = draw._getink(fill)  # type: ignore[attr-defined]
        return f if ink is None else ink

    def _build_lines(  # reduced arg count via ctx
        self,
        *,
        nodes: List[List[Any]],
        ctx: "_RenderCtx",
    ) -> Tuple[List[str], List[int], int, Dict[int, Dict[int, BytesIO]]]:
        nodes_line_to_print: List[str] = []
        widths: List[int] = []
        max_width = 0
        streams: Dict[int, Dict[int, BytesIO]] = {}

        # Measure width of a single space with the given options
        space_text_length = ctx.draw.textlength(
            " ",
            ctx.font,
            direction=ctx.direction,
            features=None,
            language=ctx.language,
            embedded_color=ctx.embedded_color,
        )
        if space_text_length == 0:
            space_text_length = 1

        for node_id, line in enumerate(nodes):
            text_line = ""
            streams[node_id] = {}
            for line_id, node in enumerate(line):
                content = node.content
                stream = None
                if node.type is NodeType.emoji:
                    stream = self._get_emoji(content)
                elif self._render_discord_emoji and node.type is NodeType.discord_emoji:
                    with suppress(Exception):
                        stream = self._get_discord_emoji(int(content))

                if stream:
                    streams[node_id][line_id] = stream

                if node.type is NodeType.text or not stream:
                    text_line += node.content
                    continue

                # Compute placeholder spaces for this emoji to match PIL layout
                with Image.open(stream).convert("RGBA") as _tmp_asset:
                    width = round(ctx.emoji_scale_factor * getattr(ctx.font, "size", 16))  # type: ignore[attr-defined]
                    ox, _oy = ctx.emoji_position_offset
                    size = round(width + ox + (ctx.node_spacing * 2))
                    space_to_add = round(size / space_text_length)
                    text_line += " " * space_to_add

            nodes_line_to_print.append(text_line)
            line_width = ctx.draw.textlength(
                text_line,
                ctx.font,
                direction=ctx.direction,
                features=ctx.features,
                language=ctx.language,
            )
            line_width_int = int(line_width)
            widths.append(line_width_int)
            max_width = max(max_width, line_width_int)

        return nodes_line_to_print, widths, max_width, streams

    @staticmethod
    def _adjust_y_for_anchor(y: float, anchor: str, num_lines: int, line_spacing: float) -> float:
        if anchor[1] == "m":
            return y - (num_lines - 1) * line_spacing / 2.0
        if anchor[1] == "d":
            return y - (num_lines - 1) * line_spacing
        return y

    @staticmethod
    def _aligned_x(x: float, anchor: str, align: str, width_difference: int) -> float:
        # First adjust for anchor (l/m/r)
        if anchor[0] == "m":
            x -= width_difference / 2.0
        elif anchor[0] == "r":
            x -= width_difference

        # Then adjust for align
        if align == "left":
            return x
        if align == "center":
            return x + width_difference / 2.0
        if align == "right":
            return x + width_difference
        raise ValueError('align must be "left", "center" or "right"')

    def _apply_font_offset(self, text_line: str, x: float, y: float, ctx: "_RenderCtx") -> Tuple[float, float]:
        # Mirror internal PIL logic to compute pixel-aligned starting point
        coord: List[int] = []
        start_fracs: List[float] = []
        for i in range(2):
            coord.append(int((x, y)[i]))
            start_fracs.append(math.modf((x, y)[i])[0])

        if ctx.ink is None:
            return x, y

        local_stroke = ctx.stroke_width
        ink = ctx.ink
        if local_stroke:
            # If stroke_fill provided, compute its ink, else reuse ink
            stroke_ink = self._resolve_ink(ctx.draw, ctx.stroke_fill) if ctx.stroke_fill is not None else ink
            if stroke_ink is not None:
                ink = stroke_ink
                local_stroke = 0

        try:
            start_tuple = (float(start_fracs[0]), float(start_fracs[1]))
            _, offset = ctx.font.getmask2(  # type: ignore[attr-defined]
                text_line,
                ctx.mode,
                *ctx.args,
                direction=ctx.direction,
                features=None,  # type: ignore[arg-type]
                language=ctx.language,
                stroke_width=local_stroke,
                anchor=ctx.anchor,
                ink=ink,
                start=start_tuple,
                **ctx.kwargs,
            )
            off = cast(Tuple[int, int], offset)
            coord[0] = coord[0] + off[0]
            coord[1] = coord[1] + off[1]
        except AttributeError:
            # Some fonts may not implement getmask2
            pass
        return float(coord[0]), float(coord[1])

    def _measure_text_width(self, content: str, ctx: "_RenderCtx") -> int:
        if HAS_GETLENGTH:
            return int(ctx.font.getlength(content, direction=ctx.direction, features=None, language=ctx.language))
        # Estimate width using draw.textlength for compatibility
        return int(
            ctx.draw.textlength(
                content,
                font=ctx.font,
                direction=ctx.direction,
                features=None,
                language=ctx.language,
            )
        )

    def _paste_emoji_for_line(
        self,
        *,
        line: List[Any],
        streams: Dict[int, BytesIO],
        x_start: float,
        y_start: float,
        ctx: "_RenderCtx",
    ) -> float:
        x = x_start
        for line_id, node in enumerate(line):
            content = node.content
            if node.type is NodeType.text or line_id not in streams:
                width = self._measure_text_width(content, ctx)
                x += ctx.node_spacing + width
                continue

            # Emoji path
            cache_key = f"{content}_{ctx.emoji_scale_factor}"
            asset: Optional[Image.Image]
            width: int
            if cache_key in self._processed_image_cache:
                asset = self._processed_image_cache[cache_key]
                width = asset.width
            else:
                with Image.open(streams[line_id]).convert("RGBA") as original_asset:
                    width = round(ctx.emoji_scale_factor * getattr(ctx.font, "size", 16))  # type: ignore[attr-defined]
                    size = width, round(math.ceil(original_asset.height / original_asset.width * width))
                    asset = original_asset.resize(size, LANCZOS)
                    self._processed_image_cache[cache_key] = asset

            ox, oy = ctx.emoji_position_offset
            self.image.paste(asset, (round(x + ox), round(y_start + oy)), asset)
            x += ctx.node_spacing + width
        return x


@dataclass
class _RenderCtx:
    draw: ImageDraw.ImageDraw
    font: FontT
    fill: ColorT
    anchor: str
    spacing: int
    node_spacing: int
    align: str
    direction: Optional[str]
    features: Optional[List[str]]
    language: Optional[str]
    stroke_width: int
    stroke_fill: ColorT
    embedded_color: bool
    args: Tuple[Any, ...]
    kwargs: Dict[str, Any]
    emoji_scale_factor: float
    emoji_position_offset: Tuple[int, int]
    mode: Any
    ink: Any
