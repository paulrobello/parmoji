"""Local font-based emoji source for parmoji."""

import hashlib
import logging
import platform
import shutil
import threading
from io import BytesIO
from typing import List, Optional

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
        self.emoji_font = None
        self.font_name = None
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
            except Exception:
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
            MD5 hash key for cache
        """
        # Include font name and size in cache key to avoid conflicts
        key_string = f"{emoji}_{self.font_name}_{self.font_size}"
        return hashlib.md5(key_string.encode()).hexdigest()

    def get_emoji(self, emoji: str, /, *, tight: bool = False, margin: int = 1) -> Optional[BytesIO]:
        """Render an emoji using local font and return as BytesIO stream.

        Args:
            emoji: The emoji character to render

        Returns:
            BytesIO stream containing the rendered emoji as PNG, or None if failed
        """
        # NOTE: Local rendering already produces a tightly-cropped image.
        # The `tight` and `margin` parameters are accepted for API
        # compatibility with HTTP-based sources but are not used.

        # Check disk cache first if enabled
        if self.disk_cache and self._cache_dir:
            cache_key = self._get_cache_key(emoji)
            cache_file = self._cache_dir / f"{cache_key}.png"

            if cache_file.exists():
                try:
                    stream = BytesIO(cache_file.read_bytes())
                    logger.debug(f"LocalFontSource: Loaded emoji '{emoji}' from disk cache")
                    return stream
                except Exception as e:
                    logger.debug(f"LocalFontSource: Failed to load from cache: {e}")

        # Thread-safe rendering
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

                # Find the bounding box of non-transparent pixels
                bbox = img.getbbox()
                if bbox:
                    # Crop to the actual emoji with a small margin
                    crop_margin = 2
                    bbox = (
                        max(0, bbox[0] - crop_margin),
                        max(0, bbox[1] - crop_margin),
                        min(size, bbox[2] + crop_margin),
                        min(size, bbox[3] + crop_margin),
                    )
                    img = img.crop(bbox)

                # Save to BytesIO
                stream = BytesIO()
                img.save(stream, format="PNG", optimize=True)
                stream.seek(0)

                # Save to disk cache if enabled
                if self.disk_cache and self._cache_dir:
                    try:
                        cache_key = self._get_cache_key(emoji)
                        cache_file = self._cache_dir / f"{cache_key}.png"
                        cache_file.write_bytes(stream.getvalue())
                        logger.debug(f"LocalFontSource: Saved emoji '{emoji}' to disk cache")
                    except Exception as e:
                        logger.debug(f"LocalFontSource: Failed to save to cache: {e}")

                return stream

            except Exception as e:
                logger.debug(f"LocalFontSource: Failed to render emoji '{emoji}': {e}")
                return None

    def get_discord_emoji(self, emoji_id: int) -> Optional[BytesIO]:
        """Discord emoji not supported by local source."""
        return None

    def clear_cache(self) -> None:
        """Clear the disk cache for this font source."""
        if self._cache_dir and self._cache_dir.exists():
            try:
                shutil.rmtree(self._cache_dir)
                self._cache_dir.mkdir(parents=True, exist_ok=True)
                logger.info(f"LocalFontSource: Cleared cache at {self._cache_dir}")
            except Exception as e:
                logger.error(f"LocalFontSource: Failed to clear cache: {e}")

    def __repr__(self) -> str:
        return f"<LocalFontSource font={self.font_name} size={self.font_size} disk_cache={self.disk_cache}>"
