"""Local font-based emoji source for parmoji."""

import hashlib
import logging
import platform
import shutil
import threading
from io import BytesIO
from typing import List, Optional, Union

from PIL import Image, ImageDraw, ImageFont

from .source import BaseSource

logger = logging.getLogger(__name__)


class LocalFontSource(BaseSource):
    """A local source that renders emoji using system fonts.

    This source is thread-safe and includes disk caching with font-aware cache keys.
    """

    def __init__(
        self,
        font_names: Optional[List[str]] = None,
        font_size: int = 72,
        disk_cache: bool = True,
        prime_on_init: bool = True,
    ):
        """Initialize local font source.

        Args:
            font_names: List of font names to try in order
            font_size: Size for rendering emoji (default 72 for good quality)
            disk_cache: Enable disk caching of rendered emoji
            prime_on_init: Prime cache with common emojis on initialization
        """
        super().__init__(disk_cache=disk_cache)

        self.font_size = font_size
        self.emoji_font: Optional[Union[ImageFont.FreeTypeFont, ImageFont.ImageFont]] = None
        self.font_name: Optional[str] = None
        self._render_lock = threading.Lock()

        # Default fonts that support emoji on various systems
        if font_names is None:
            system = platform.system()
            if system == "Darwin":  # macOS
                font_names = ["Apple Color Emoji", "Monaco", "Menlo", "SF Pro Display"]
            elif system == "Windows":
                font_names = ["Segoe UI Emoji", "Segoe UI Symbol", "Consolas"]
            else:  # Linux
                font_names = ["Noto Color Emoji", "Noto Emoji", "DejaVu Sans"]

        # Try to load a font that can render emoji
        for font_name in font_names:
            try:
                self.emoji_font = ImageFont.truetype(font_name, self.font_size)
                self.font_name = font_name
                logger.debug(f"LocalFontSource: Loaded {font_name} for emoji rendering")
                break
            except OSError:
                # QA-003: truetype raises OSError when the font is missing or
                # cannot be parsed; try the next candidate.
                continue

        if not self.emoji_font:
            # Fall back to default font
            self.emoji_font = ImageFont.load_default()
            self.font_name = "default"
            logger.warning("LocalFontSource: Could not load emoji font, using default")

        # Prime cache with common emojis if requested
        if prime_on_init and disk_cache:
            self.prime_cache()

    def _get_cache_key(self, emoji: str) -> str:
        """Generate a cache key that includes font name and size.

        Args:
            emoji: The emoji character

        Returns:
            blake2b hash key for cache
        """
        # SEC-006: blake2b(digest_size=16) for non-cryptographic cache keys
        # (32-char hex, same length as the former MD5; only hash values change,
        # invalidating prior on-disk entries — cache rebuilds).
        # Include font name and size in cache key to avoid conflicts
        key_string = f"{emoji}_{self.font_name}_{self.font_size}"
        return hashlib.blake2b(key_string.encode(), digest_size=16).hexdigest()

    def _cache_key_for(self, emoji: str, *, tight: bool, margin: int) -> str:
        """Cache key distinguishing the tight variant from the base render.

        LocalFontSource always crops to the glyph bbox, but a tight=True
        request with a custom margin produces a different crop and so must
        not alias the base cache entry (ARC-008).
        """
        base = self._get_cache_key(emoji)
        return f"{base}_t{max(0, int(margin))}" if tight else base

    def get_emoji(self, emoji: str, /, *, tight: bool = False, margin: int = 1) -> Optional[BytesIO]:
        """Render an emoji using the local font and return a PNG stream.

        ARC-008: local rendering always crops to the glyph's alpha bounding
        box (there is no CDN "safe zone" to remove), so ``tight`` is always
        effectively honored. ``tight``/``margin`` now drive the crop padding
        instead of being ignored: ``tight=False`` keeps the 2px default
        padding (byte-for-byte unchanged output, same cache key), and
        ``tight=True`` applies the passed ``margin``. Disk-cache I/O goes
        through ``BaseSource._cache_get``/``_cache_put``.

        Args:
            emoji: The emoji character to render
            tight: When True, use ``margin`` as the crop padding; when False
                use the default 2px padding.
            margin: Crop padding in pixels (used only when ``tight`` is True).

        Returns:
            BytesIO stream containing the rendered emoji as PNG, or None if failed
        """
        cache_key = self._cache_key_for(emoji, tight=tight, margin=margin)
        cached = self._cache_get(cache_key)
        if cached is not None:
            logger.debug(f"LocalFontSource: Loaded emoji '{emoji}' from disk cache")
            return BytesIO(cached)

        crop_margin = margin if tight else 2
        with self._render_lock:
            try:
                # Create a transparent image slightly larger than needed
                size = int(self.font_size * 1.5)
                img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
                draw = ImageDraw.Draw(img)

                # Get the bounding box of the emoji to center it properly
                bbox = draw.textbbox((0, 0), emoji, font=self.emoji_font)
                text_width = bbox[2] - bbox[0]
                text_height = bbox[3] - bbox[1]

                # Center the emoji in the image
                x = (size - text_width) // 2 - bbox[0]
                y = (size - text_height) // 2 - bbox[1]

                # Render the emoji in white (will be recolored by parmoji)
                draw.text((x, y), emoji, font=self.emoji_font, fill=(255, 255, 255, 255))

                # Find the bounding box of non-transparent pixels and crop.
                bbox = img.getbbox()
                if bbox:
                    bbox = (
                        max(0, bbox[0] - crop_margin),
                        max(0, bbox[1] - crop_margin),
                        min(size, bbox[2] + crop_margin),
                        min(size, bbox[3] + crop_margin),
                    )
                    img = img.crop(bbox)

                stream = BytesIO()
                img.save(stream, format="PNG", optimize=True)
                png_bytes = stream.getvalue()
                stream.seek(0)

                self._cache_put(cache_key, png_bytes)
                logger.debug(f"LocalFontSource: Saved emoji '{emoji}' to disk cache")
                return stream

            except (OSError, ValueError) as e:
                # QA-003: realistic render-path failures are Pillow I/O errors
                # (OSError, which also covers Image.UnidentifiedImageError) and
                # bad-argument ValueErrors from textbbox/text.
                logger.debug(f"LocalFontSource: Failed to render emoji '{emoji}': {e}")
                return None

    def get_discord_emoji(self, emoji_id: int, /, *, animated: bool = False) -> Optional[BytesIO]:
        """Discord emoji not supported by local source."""
        return None

    def clear_cache(self) -> None:
        """Clear the disk cache for this font source."""
        if self._cache_dir and self._cache_dir.exists():
            try:
                shutil.rmtree(self._cache_dir)
                self._cache_dir.mkdir(parents=True, exist_ok=True)
                logger.info(f"LocalFontSource: Cleared cache at {self._cache_dir}")
            except OSError as e:
                # QA-003: shutil.rmtree / mkdir raise OSError on filesystem failures.
                logger.error(f"LocalFontSource: Failed to clear cache: {e}")

    def __repr__(self) -> str:
        return f"<LocalFontSource font={self.font_name} size={self.font_size} disk_cache={self.disk_cache}>"
