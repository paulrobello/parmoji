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
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Dict,
    List,
    Optional,
    SupportsInt,
    Tuple,
    Type,
    TypeVar,
    Union,
    cast,
    overload,
)

from PIL import Image, ImageDraw, ImageFont

from .helpers import NodeType, _measure_text_width, getsize, to_nodes
from .source import BaseSource, HTTPBasedSource, Twemoji

logger = logging.getLogger(__name__)

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportAttributeAccessIssue=false

# ARC-009: PIL_VERSION / HAS_GETLENGTH live in helpers (single source of truth).

# Check for Pillow 10+ resampling with safe fallback
try:
    from PIL.Image import Resampling as _Resampling  # type: ignore[attr-defined]

    LANCZOS: Any = _Resampling.LANCZOS
except (ImportError, AttributeError):
    # QA-003: narrow to the two real failure modes — old Pillow without
    # ``Resampling`` (ImportError) or without the ``LANCZOS`` attr.
    # Fallback using getattr to satisfy type stubs
    LANCZOS: Any = getattr(Image, "LANCZOS", getattr(Image, "BICUBIC", 1))

if TYPE_CHECKING:
    FontT = Union[ImageFont.ImageFont, ImageFont.FreeTypeFont, ImageFont.TransposedFont]
    ColorBaseT = Union[int, Tuple[int, int, int], Tuple[int, int, int, int], str]
else:
    # Runtime-only aliases for readability
    FontT = Any  # type: ignore[assignment]
    ColorBaseT = Any  # type: ignore[assignment]

ColorT = Optional[ColorBaseT]


P = TypeVar("P", bound="Parmoji")

# ARC-017: LRUCacheDict is generic over key/value types so the three Parmoji
# caches (str→bytes, tuple[int,bool]→bytes, str→Image.Image) get real types
# without per-line `# type: ignore` comments.
K = TypeVar("K")
V = TypeVar("V")
_D = TypeVar("_D")

__all__ = ("Parmoji",)

# Module-level constants for small magic values
ANCHOR_LEN: int = 2


class LRUCacheDict(OrderedDict[K, V]):
    """Bounded LRU cache with internal locking (ARC-017: generic over K/V).

    Generic so each instance carries concrete key/value types — the three
    Parmoji caches instantiate it as ``LRUCacheDict[str, bytes]``,
    ``LRUCacheDict[tuple[int, bool], bytes]``, and ``LRUCacheDict[str, Image.Image]``.
    Thread-safe via an internal lock around mutation and LRU re-ordering.
    """

    def __init__(self, maxsize: int = 1000) -> None:
        super().__init__()
        self.maxsize: int = maxsize
        self._lock: threading.Lock = threading.Lock()

    def __setitem__(self, key: K, value: V) -> None:
        with self._lock:
            if key in self:
                # Move to end (most recently used)
                self.move_to_end(key)
            super().__setitem__(key, value)
            if len(self) > self.maxsize:
                # ARC-007: drop oldest entry. Cached values are immutable bytes
                # (or Images owned by the cache), so there is no closeable
                # resource to release on eviction — closing them here was the
                # source of a use-after-close race with concurrent readers.
                del self[next(iter(self))]

    def __getitem__(self, key: K) -> V:
        with self._lock:
            value = super().__getitem__(key)
            # Move to end (most recently used)
            self.move_to_end(key)
            return value

    @overload
    def get(self, key: K) -> Optional[V]: ...
    @overload
    def get(self, key: K, default: _D) -> Union[V, _D]: ...
    def get(self, key: K, default: Any = None) -> Any:
        # Avoid calling __getitem__ while holding the lock (would deadlock)
        with self._lock:
            if key in self:
                value = super().__getitem__(key)
                # Move to end (most recently used)
                super().move_to_end(key)
                return value
            return default


def _coerce_source(
    source: Union[BaseSource, Type[BaseSource]],
    *,
    disk_cache: bool,
) -> BaseSource:
    """Normalize a source argument to a ready ``BaseSource`` instance (ARC-016).

    Accepts either a ``BaseSource`` subclass (instantiated with ``disk_cache``)
    or an existing ``BaseSource`` instance (returned unchanged). Raises
    ``TypeError`` for anything else. Extracted from ``Parmoji.__init__`` so the
    constructor only orchestrates rather than branching on source shape.
    """
    if isinstance(source, type):
        if not issubclass(source, BaseSource):
            raise TypeError(f"source must inherit from BaseSource, not {source}.")
        return source(disk_cache=disk_cache)
    if not isinstance(source, BaseSource):
        raise TypeError(f"source must inherit from BaseSource, not {source.__class__}.")
    return source


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

        # ARC-016: source class-vs-instance coercion lives in a factory so the
        # constructor body stays a linear sequence of attribute assignments.
        self.source: BaseSource = _coerce_source(source, disk_cache=disk_cache)

        self._cache: bool = cache
        self._cache_size: int = cache_size
        self._closed: bool = False
        self._new_draw: bool = False

        self._render_discord_emoji: bool = render_discord_emoji
        self._default_emoji_scale_factor: float = emoji_scale_factor
        self._default_emoji_position_offset: Tuple[int, int] = emoji_position_offset

        # Use LRU cache with size limit to prevent memory leaks.
        # QA-001: guard the discord half with max(1, ...) so cache_size <= 1
        # does not produce a maxsize=0 LRU that evicts on every insert.
        self._emoji_cache: LRUCacheDict[str, bytes] = LRUCacheDict(maxsize=cache_size)
        self._discord_emoji_cache: LRUCacheDict[Tuple[int, bool], bytes] = LRUCacheDict(maxsize=max(1, cache_size // 2))

        # ARC-006: bound the processed-image cache. This was an unbounded dict
        # keyed by "{emoji}_{scale}", so every distinct (emoji, scale) pair
        # permanently retained a full RGBA Image — a memory leak for long-lived
        # renderers. It is now a third LRU sharing the cache budget. Values are
        # not closed on eviction (ARC-007): Images are GC'd when the reference
        # drops.
        self._processed_image_cache: LRUCacheDict[str, Image.Image] = LRUCacheDict(maxsize=cache_size)

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

        # ARC-003: delegate client lifecycle to the source. Previously this
        # only rebuilt a requests Session, leaving the default httpx client
        # closed and dead after a close/reopen. HTTPBasedSource.reopen()
        # recreates whichever backend is configured.
        if isinstance(self.source, HTTPBasedSource):
            self.source.reopen()

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
            # ARC-007: caches now hold immutable bytes / owned Images, so there
            # are no closeable streams to sweep. Reset to fresh bounded LRU
            # instances (clear() would also suffice; the rebuild mirrors the
            # original reset behaviour for the now-bounded processed cache).
            self._emoji_cache = LRUCacheDict(maxsize=self._cache_size)
            self._discord_emoji_cache = LRUCacheDict(maxsize=max(1, self._cache_size // 2))
            self._processed_image_cache = LRUCacheDict(maxsize=self._cache_size)

        self._closed = True

    def _create_draw(self) -> None:
        if self.draw is None:
            self._new_draw = True
            self.draw = ImageDraw.Draw(self.image)

    def _get_cached(
        self,
        key: K,
        cache: "LRUCacheDict[K, bytes]",
        fetch_fn: Callable[[], Optional[BytesIO]],
    ) -> Optional[BytesIO]:
        # QA-008: _get_emoji and _get_discord_emoji differed only in cache and
        # source method; this helper owns the shared lookup->fetch->read-bytes
        # ->store->BytesIO shape. ARC-007: the cache stores immutable bytes and
        # each caller wraps a fresh BytesIO over them, so eviction cannot close
        # a stream another thread is reading. The LRU's own lock is the single
        # lock for each cache; no separate _cache_lock is needed.
        if self._cache:
            cached = cache.get(key)
            if cached is not None:
                return BytesIO(cached)

        stream = fetch_fn()
        if stream is None:
            return None
        stream.seek(0)
        raw = stream.read()
        if self._cache:
            cache[key] = raw
        return BytesIO(raw)

    def _get_emoji(self, emoji: str, /) -> Optional[BytesIO]:
        return self._get_cached(emoji, self._emoji_cache, lambda: self.source.get_emoji(emoji))

    def _get_discord_emoji(self, emoji_id: SupportsInt, /, *, animated: bool = False) -> Optional[BytesIO]:
        # ARC-002: the cache key carries the animated flag so the gif and png
        # variants of one snowflake do not alias each other.
        emoji_id = int(emoji_id)
        cache_key: tuple[int, bool] = (emoji_id, animated)
        return self._get_cached(
            cache_key,
            self._discord_emoji_cache,
            lambda: self.source.get_discord_emoji(emoji_id, animated=animated),
        )

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

    def text(  # noqa: PLR0913, PLR0917 - public API mirrors Pillow's ImageDraw.text
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
            ``direction``, ``features``, and ``language`` mirror Pillow's
            ``ImageDraw.text`` parameters and are forwarded to Pillow, but
            Parmoji's emoji handling does not fully honor them:
            ``direction="ttb"`` is rejected for multiline text, and ``features``
            is ignored during emoji-width measurement.

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
        """Cleanup resources if not properly closed (guarded backstop).

        ARC-013: the context manager (:meth:`close` / ``with``) is the supported
        path. ``__del__`` is only a best-effort backstop that can fire during
        interpreter shutdown or before ``__init__`` finished setting attributes,
        so every attribute it reads is getattr-guarded (defaulting to a state
        that skips cleanup) and any error — including interpreter-shutdown
        attribute errors — is swallowed silently.
        """
        with suppress(Exception):
            if not getattr(self, "_closed", True):
                self.close()

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
                        stream = self._get_discord_emoji(int(content), animated=node.animated)

                if stream:
                    streams[node_id][line_id] = stream

                if node.type is NodeType.text or not stream:
                    text_line += node.content
                    continue

                # Compute placeholder spaces for this emoji to match PIL layout
                try:
                    with Image.open(stream).convert("RGBA") as _tmp_asset:
                        width = round(ctx.emoji_scale_factor * getattr(ctx.font, "size", 16))  # type: ignore[attr-defined]
                        ox, _oy = ctx.emoji_position_offset
                        size = round(width + ox + (ctx.node_spacing * 2))
                        space_to_add = round(size / space_text_length)
                        text_line += " " * space_to_add
                except Image.DecompressionBombError:
                    # SEC-001: refuse a decompression bomb; treat the emoji as
                    # absent so the rest of the line still renders.
                    logger.warning("Refusing decompression-bomb emoji %r during layout", content)
                    streams[node_id].pop(line_id, None)
                    text_line += node.content

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
                width = _measure_text_width(
                    content, ctx.font, draw=ctx.draw, direction=ctx.direction, language=ctx.language
                )
                x += ctx.node_spacing + width
                continue

            # Emoji path. ARC-006: processed-image cache is now a bounded LRU;
            # QA-015: go through its .get()/__setitem__ so its own lock guards
            # mutation (previously this plain-dict access raced under concurrent
            # text() calls).
            cache_key = f"{content}_{ctx.emoji_scale_factor}"
            # Both branches below assign a concrete Image.Image; declared
            # non-Optional so the .get() Any does not taint the downstream use.
            asset: Image.Image
            width: int
            try:
                cached_asset = self._processed_image_cache.get(cache_key)
                if cached_asset is not None:
                    asset = cached_asset
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
            except Image.DecompressionBombError:
                # SEC-001: refuse a decompression bomb; advance past the
                # placeholder so the rest of the line still renders.
                logger.warning("Refusing decompression-bomb emoji %r during paste", content)
                width = round(ctx.emoji_scale_factor * getattr(ctx.font, "size", 16))  # type: ignore[attr-defined]
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
