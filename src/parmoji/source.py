"""Emoji image sources for Parmoji.

This module contains the source abstraction and concrete implementations used
to fetch emoji images. Sources may be purely local (font-based) or HTTP-based
with retry and disk-caching support.

Key classes:
- `BaseSource`: minimal interface with optional disk cache helpers.
- `HTTPBasedSource`: robust HTTP client with retries and a persistent
  failed-request set to avoid repeated 404s.
- `EmojiCDNSource` and its styles: wrappers around emojicdn.elk.sh.
- `DiscordEmojiSourceMixin`: adds support for Discord custom emoji.

Notes
-----
- All public methods prefer explicit typing and short, single-purpose helpers.
- Parameter names avoid shadowing builtins (e.g. `emoji_id` vs `id`).
- Disk cache uses XDG base directories as per the repository guidelines.
"""

import hashlib
import json
import logging
import os
import time
import unicodedata
from abc import ABC, abstractmethod
from contextlib import suppress
from io import BytesIO
from pathlib import Path
from typing import Any, ClassVar, Dict, Optional, Set
from urllib.error import HTTPError, URLError
from urllib.parse import quote_plus, urlparse
from urllib.request import Request, urlopen

from PIL import Image

# SEC-001: explicit decompression-bomb ceiling for untrusted CDN bytes.
# Pillow's default (~89 Mpx) is far larger than any emoji needs; tighten to
# 20 Mpx (still well above the largest emoji ~1 Mpx). Only ever tighten the
# host application's setting, never relax it.
_MAX_IMAGE_PIXELS_CEILING: int = 20_000_000
if Image.MAX_IMAGE_PIXELS is None or Image.MAX_IMAGE_PIXELS > _MAX_IMAGE_PIXELS_CEILING:
    Image.MAX_IMAGE_PIXELS = _MAX_IMAGE_PIXELS_CEILING

try:
    import requests
    from requests.adapters import HTTPAdapter

    try:
        from urllib3.util import Retry  # type: ignore
    except Exception:  # pragma: no cover - older requests vendored urllib3
        from requests.packages.urllib3.util.retry import Retry  # type: ignore
    _has_requests = True
except ImportError:  # type: ignore[no-redef]
    requests = None  # type: ignore[assignment]
    HTTPAdapter = None  # type: ignore[assignment]
    Retry = None  # type: ignore[assignment]
    _has_requests = False

try:
    import httpx

    _has_httpx = True
except ImportError:
    httpx = None
    _has_httpx = False

try:
    # Optional helper libraries; imported at module import to satisfy lint rules
    import emoji as _emoji  # type: ignore
except Exception:  # pragma: no cover - optional
    _emoji = None  # type: ignore[assignment]

try:
    from xdg_base_dirs import xdg_cache_home  # type: ignore
except Exception:  # pragma: no cover - optional
    xdg_cache_home = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

__all__ = (
    "BaseSource",
    "HTTPBasedSource",
    "DiscordEmojiSourceMixin",
    "EmojiCDNSource",
    "TwitterEmojiSource",
    "AppleEmojiSource",
    "GoogleEmojiSource",
    "MicrosoftEmojiSource",
    "FacebookEmojiSource",
    "MessengerEmojiSource",
    "EmojidexEmojiSource",
    "JoyPixelsEmojiSource",
    "SamsungEmojiSource",
    "WhatsAppEmojiSource",
    "MozillaEmojiSource",
    "OpenmojiEmojiSource",
    "TwemojiEmojiSource",
    "FacebookMessengerEmojiSource",
    "Twemoji",
    "Openmoji",
)

MAX_EMOJI_SEQ_LEN: int = 10  # Reasonable max length for emoji sequences


def is_valid_emoji(emoji: str) -> bool:
    """Validate that a string contains a valid emoji.

    Args:
        emoji: String to validate

    Returns:
        True if the string contains a valid emoji character
    """
    if not emoji or len(emoji) > MAX_EMOJI_SEQ_LEN:
        return False

    ok = False
    # Prefer robust library-based detection when available
    try:
        if _emoji is not None:
            if getattr(_emoji, "emoji_count", None) and _emoji.emoji_count(emoji) > 0:  # type: ignore[attr-defined]
                ok = True
            else:
                # Strip VS-16/ZWJ and consult EMOJI_DATA / is_emoji on base grapheme
                base = emoji.replace("\ufe0f", "").replace("\u200d", "")
                if base and ((hasattr(_emoji, "EMOJI_DATA") and base in _emoji.EMOJI_DATA) or _emoji.is_emoji(base)):
                    ok = True
    except Exception:
        # Fall through to heuristics
        ok = False

    # Heuristic fallback without the library.
    # Reject known text-only dingbats unless VS-16 present.
    if not ok:
        dingbat_invalid = "\ufe0f" not in emoji and any(ch in {"\u2713", "\u2717", "\u2714", "\u2716"} for ch in emoji)
        if dingbat_invalid:
            return False

        for char in emoji:
            category = unicodedata.category(char)
            if category in ("So", "Sk", "Mn"):
                ok = True
                break
            if char in ("\u200d", "\ufe0f", "\ufe0e"):
                ok = True
                break

    return ok


class BaseSource(ABC):
    """The base class for an emoji image source.

    Attributes:
        disk_cache: Whether to cache emojis to disk
    """

    def __init__(self, disk_cache: bool = False):
        """Initialize base source.

        Args:
            disk_cache: Whether to enable disk caching
        """
        self.disk_cache: bool = disk_cache
        self._cache_dir: Optional[Path] = None
        self._primed_emojis: Set[str] = set()

        if disk_cache:
            # Use XDG base directory for caches
            try:
                base_cache = Path(xdg_cache_home()) if xdg_cache_home else (Path.home() / ".cache")
            except Exception:
                base_cache = Path.home() / ".cache"
            self._cache_dir = base_cache / "par-term" / "parmoji" / self.__class__.__name__
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            logger.debug(f"{self.__class__.__name__}: Disk cache enabled at {self._cache_dir}")

    @abstractmethod
    def get_emoji(self, emoji: str, /, *, tight: bool = False, margin: int = 1) -> Optional[BytesIO]:
        """Retrieves a :class:`io.BytesIO` stream for the image of the given emoji.

        Parameters
        ----------
        emoji: str
            The emoji to retrieve.

        Parameters
        ----------
        tight: bool, default False
            When True, returns an image cropped to the non-transparent alpha
            bounding box (expanded by ``margin``). Intended to remove the
            "safe-zone" padding present in some emoji sets (e.g., Twemoji)
            so the visible glyph fills the intended cell area.
        margin: int, default 1
            Extra pixels to include around the content bounding box when
            ``tight`` is True. The margin is clamped to the image bounds.

        Returns
        -------
        :class:`io.BytesIO`
            A bytes stream of the emoji.
        None
            An image for the emoji could not be found.
        """
        raise NotImplementedError

    @abstractmethod
    def get_discord_emoji(self, emoji_id: int, /) -> Optional[BytesIO]:
        """Retrieves a :class:`io.BytesIO` stream for the image of the given Discord emoji.

        Parameters
        ----------
        emoji_id: int
            The snowflake ID of the Discord emoji.

        Returns
        -------
        :class:`io.BytesIO`
            A bytes stream of the emoji.
        None
            An image for the emoji could not be found.
        """
        raise NotImplementedError

    def prime_cache(self, emojis: Optional[Set[str]] = None) -> None:
        """Prime the disk cache with commonly used emojis.

        Args:
            emojis: Set of emoji strings to prime. If None, uses a default set.
        """
        if not self.disk_cache:
            return

        if emojis is None:
            # Default common emojis to prime
            emojis = {
                "😀",
                "😃",
                "😄",
                "😁",
                "😅",
                "😂",
                "🤣",
                "😊",
                "😇",
                "🙂",
                "😍",
                "🥰",
                "😘",
                "😗",
                "😙",
                "😚",
                "😋",
                "😛",
                "😜",
                "🤪",
                "😝",
                "🤑",
                "🤗",
                "🤭",
                "🤫",
                "🤔",
                "😐",
                "😑",
                "😶",
                "😏",
                "😒",
                "🙄",
                "😬",
                "🤥",
                "😌",
                "😔",
                "😪",
                "🤤",
                "😴",
                "😷",
                "🤒",
                "🤕",
                "🤢",
                "🤮",
                "🤧",
                "😵",
                "🤯",
                "🤠",
                "😎",
                "🤓",
                "🧐",
                "😕",
                "😟",
                "🙁",
                "☹️",
                "😮",
                "😯",
                "😲",
                "😳",
                "🥺",
                "😦",
                "😧",
                "😨",
                "😰",
                "😥",
                "😢",
                "😭",
                "😱",
                "😖",
                "😣",
                "😞",
                "😓",
                "😩",
                "😫",
                "🥱",
                "😤",
                "😡",
                "😠",
                "🤬",
                "😈",
                "👿",
                "💀",
                "☠️",
                "💩",
                "🤡",
                "👹",
                "👺",
                "👻",
                "👽",
                "👾",
                "🤖",
                "😺",
                "😸",
                "😹",
                "😻",
                "😼",
                "😽",
                "🙀",
                "😿",
                "😾",
                "🙈",
                "🙉",
                "🙊",
                "💋",
                "💌",
                "💘",
                "💝",
                "💖",
                "💗",
                "💓",
                "💞",
                "💕",
                "💟",
                "❣️",
                "💔",
                "❤️",
                "🧡",
                "💛",
                "💚",
                "💙",
                "💜",
                "🤎",
                "🖤",
                "🤍",
                "💯",
                "💢",
                "💥",
                "💫",
                "💦",
                "💨",
                "🕳️",
                "💣",
                "💬",
                "👁️‍🗨️",
                "🗨️",
                "🗯️",
                "💭",
                "💤",
                "👋",
                "🤚",
                "🖐️",
                "✋",
                "🖖",
                "👌",
                "🤏",
                "✌️",
                "🤞",
                "🤟",
                "🤘",
                "🤙",
                "👈",
                "👉",
                "👆",
                "🖕",
                "👇",
                "☝️",
                "👍",
                "👎",
                "✊",
                "👊",
                "🤛",
                "🤜",
                "👏",
                "🙌",
                "👐",
                "🤲",
                "🤝",
                "🙏",
                "✍️",
                "💅",
                "🤳",
                "💪",
                "🦾",
                "🦵",
                "🦿",
                "🦶",
                "👂",
                "🦻",
                "👃",
                "🧠",
                "🦷",
                "🦴",
                "👀",
                "👁️",
                "👅",
                "👄",
                "🩸",
                "👶",
            }

        logger.info(f"{self.__class__.__name__}: Priming cache with {len(emojis)} emojis...")
        primed_count = 0

        for emoji in emojis:
            if emoji in self._primed_emojis:
                continue

            try:
                # Try to get the emoji (will cache it)
                stream = self.get_emoji(emoji)
                if stream:
                    stream.close()
                    primed_count += 1
                    self._primed_emojis.add(emoji)
            except Exception as e:
                logger.debug(f"Failed to prime emoji {emoji}: {e}")

        logger.info(f"{self.__class__.__name__}: Primed {primed_count} emojis to cache")

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} disk_cache={self.disk_cache}>"


class HTTPBasedSource(BaseSource):
    """Represents an HTTP-based source with retry logic and timeouts."""

    REQUEST_KWARGS: ClassVar[Dict[str, Any]] = {"headers": {"User-Agent": "Mozilla/5.0 (Parmoji/2.0)"}}

    TIMEOUT: ClassVar[float] = 10.0  # 10 second timeout
    MAX_RETRIES: ClassVar[int] = 3
    RETRY_BACKOFF: ClassVar[float] = 0.3

    # SEC-001: hard cap on response body size (2 MiB is generous for emoji).
    MAX_RESPONSE_BYTES: ClassVar[int] = 2 * 1024 * 1024
    # SEC-002: only https requests to these hosts are honoured. The final
    # (post-redirect) destination is re-checked in each backend helper.
    ALLOWED_SCHEMES: ClassVar[frozenset[str]] = frozenset({"https"})
    ALLOWED_HOSTS: ClassVar[frozenset[str]] = frozenset({"emojicdn.elk.sh", "cdn.discordapp.com"})

    def __init__(self, disk_cache: bool = False) -> None:
        super().__init__(disk_cache)

        # Initialize failed requests cache
        self._failed_requests: Set[str] = set()
        self._failed_cache_file: Optional[Path] = None

        # Load persistent failed requests cache
        if disk_cache and self._cache_dir:
            self._failed_cache_file = self._cache_dir / "failed_requests.json"
            if self._failed_cache_file.exists():
                try:
                    with open(self._failed_cache_file, "r") as f:
                        data = json.load(f)
                        self._failed_requests = set(data.get("failed", []))
                        logger.debug(f"Loaded {len(self._failed_requests)} failed requests from cache")
                except Exception as e:
                    logger.debug(f"Failed to load failed requests cache: {e}")
                    self._failed_requests = set()

        # Prefer httpx for async-friendly operations
        if _has_httpx:
            # Create httpx client with connection pooling and retry
            # Using sync client that's thread-safe and doesn't block event loop
            assert httpx is not None
            self._httpx_client = httpx.Client(
                timeout=httpx.Timeout(self.TIMEOUT),
                limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
                headers={"User-Agent": "Mozilla/5.0 (Parmoji/2.0)"},
                follow_redirects=True,
            )
            self._requests_session = None
        elif _has_requests:
            self._httpx_client = None
            assert requests is not None and HTTPAdapter is not None and Retry is not None
            self._requests_session = requests.Session()
            # Configure retry strategy
            retry_strategy = Retry(
                total=self.MAX_RETRIES,
                backoff_factor=self.RETRY_BACKOFF,
                status_forcelist=[429, 500, 502, 503, 504],
            )
            adapter = HTTPAdapter(max_retries=retry_strategy)
            self._requests_session.mount("http://", adapter)
            self._requests_session.mount("https://", adapter)
        else:
            self._httpx_client = None
            self._requests_session = None

    def __del__(self) -> None:
        """Clean up session on deletion."""
        if _has_httpx and hasattr(self, "_httpx_client") and self._httpx_client:
            with suppress(Exception):
                self._httpx_client.close()
        if _has_requests and hasattr(self, "_requests_session") and self._requests_session:
            with suppress(Exception):
                self._requests_session.close()

    def _mark_request_failed(self, key: str) -> None:
        """Mark a request as failed and save to persistent cache."""
        self._failed_requests.add(key)

        # Save to persistent cache if enabled
        if self._failed_cache_file:
            try:
                with open(self._failed_cache_file, "w") as f:
                    json.dump({"failed": list(self._failed_requests)}, f)
            except Exception as e:
                logger.debug(f"Failed to save failed requests cache: {e}")

    def _is_request_failed(self, key: str) -> bool:
        """Check if a request has previously failed."""
        return key in self._failed_requests

    def _clear_failed_request(self, key: str) -> None:
        """Remove a key from the failed requests cache and persist."""
        if key in self._failed_requests:
            self._failed_requests.discard(key)
            if self._failed_cache_file:
                try:
                    with open(self._failed_cache_file, "w") as f:
                        json.dump({"failed": list(self._failed_requests)}, f)
                except Exception as e:
                    logger.debug(f"Failed to persist cleared failed cache: {e}")

    def clear_failed_cache(self) -> None:
        """Clear the failed requests cache."""
        self._failed_requests.clear()
        if self._failed_cache_file and self._failed_cache_file.exists():
            try:
                self._failed_cache_file.unlink()
                logger.info("Cleared failed requests cache")
            except Exception as e:
                logger.debug(f"Failed to delete failed cache file: {e}")

    def request(self, url: str) -> bytes:
        """Makes a GET request to the given URL with timeout and retry.

        Prefers httpx, then requests, then urllib, delegating to small helpers
        to keep this wrapper simple for lint readability.

        SEC-002: the URL scheme and host are validated against
        :attr:`ALLOWED_SCHEMES` / :attr:`ALLOWED_HOSTS` before any network
        I/O, and each backend re-checks the final (post-redirect) URL plus
        the response ``Content-Type`` and size.
        """
        self._validate_url(url, source_label="request URL")
        if _has_httpx and hasattr(self, "_httpx_client") and self._httpx_client:
            return self._request_httpx(url)
        if _has_requests and self._requests_session:
            return self._request_requests(url)
        return self._request_urllib(url)

    # --- Request helpers (split to reduce branches in request) ---

    def _validate_url(self, url: str, *, source_label: str) -> None:
        """Reject URLs whose scheme or host is not on the allowlist.

        Raises ``ValueError`` so callers can distinguish validation failures
        from transient network errors; backend retry loops let it propagate
        immediately rather than retrying a deterministic rejection.
        """
        parsed = urlparse(url)
        if parsed.scheme not in self.ALLOWED_SCHEMES:
            raise ValueError(
                f"Refusing {source_label}: scheme {parsed.scheme!r} not in allowlist {sorted(self.ALLOWED_SCHEMES)}"
            )
        host = parsed.hostname
        if not host or host not in self.ALLOWED_HOSTS:
            raise ValueError(f"Refusing {source_label}: host {host!r} not in allowlist {sorted(self.ALLOWED_HOSTS)}")

    def _validate_response(
        self,
        *,
        content_type: str,
        content_length: Optional[int],
        final_url: str,
    ) -> None:
        """Validate a fetched response (Content-Type, size, final host).

        Re-applies the host allowlist to the post-redirect URL so a CDN
        redirect to an attacker host cannot bypass :meth:`_validate_url`.
        """
        self._validate_url(final_url, source_label="redirected URL")

        ct = (content_type or "").split(";", 1)[0].strip().lower()
        if ct and not ct.startswith("image/"):
            raise ValueError(f"Refusing response: Content-Type {ct!r} is not an image type")

        if content_length is not None and content_length > self.MAX_RESPONSE_BYTES:
            raise ValueError(
                f"Refusing response: Content-Length {content_length} exceeds "
                f"MAX_RESPONSE_BYTES={self.MAX_RESPONSE_BYTES}"
            )

    def _check_body_size(self, data: bytes) -> bytes:
        """Final defense-in-depth check on the actual body size."""
        if len(data) > self.MAX_RESPONSE_BYTES:
            raise ValueError(
                f"Refusing response: body {len(data)} bytes exceeds MAX_RESPONSE_BYTES={self.MAX_RESPONSE_BYTES}"
            )
        return data

    def _request_httpx(self, url: str) -> bytes:
        assert _has_httpx and self._httpx_client is not None
        last_error: Optional[Exception] = None
        for attempt in range(self.MAX_RETRIES):
            try:
                response = self._httpx_client.get(url)
                response.raise_for_status()
                cl_raw = response.headers.get("Content-Length", "")
                cl = int(cl_raw) if cl_raw.isdigit() else None
                self._validate_response(
                    content_type=response.headers.get("Content-Type", ""),
                    content_length=cl,
                    final_url=str(response.url),
                )
                return self._check_body_size(response.content)
            except ValueError:
                # Validation failures are deterministic; never retry.
                raise
            except Exception as e:
                last_error = e
                if attempt < self.MAX_RETRIES - 1:
                    time.sleep(self.RETRY_BACKOFF * (2**attempt))
                else:
                    logger.warning(f"Request failed for {url} after {self.MAX_RETRIES} attempts: {e}")
        assert last_error is not None
        raise last_error

    def _request_requests(self, url: str) -> bytes:
        assert _has_requests and self._requests_session is not None
        try:
            with self._requests_session.get(url, timeout=self.TIMEOUT, **self.REQUEST_KWARGS) as response:  # type: ignore[call-arg]
                response.raise_for_status()
                cl_raw = response.headers.get("Content-Length", "")
                cl = int(cl_raw) if cl_raw.isdigit() else None
                self._validate_response(
                    content_type=response.headers.get("Content-Type", ""),
                    content_length=cl,
                    final_url=str(response.url),
                )
                return self._check_body_size(response.content)
        except Exception as e:
            logger.warning(f"Request failed for {url}: {e}")
            raise

    def _request_urllib(self, url: str) -> bytes:
        last_error: Optional[Exception] = None
        for attempt in range(self.MAX_RETRIES):
            try:
                req = Request(url, **self.REQUEST_KWARGS)
                with urlopen(req, timeout=self.TIMEOUT) as response:  # noqa: S310 (trusted URL built by source)
                    cl_raw = response.getheader("Content-Length", "")
                    cl = int(cl_raw) if cl_raw and cl_raw.isdigit() else None
                    self._validate_response(
                        content_type=response.getheader("Content-Type", ""),
                        content_length=cl,
                        final_url=response.geturl(),
                    )
                    data = response.read()
                return self._check_body_size(data)
            except (HTTPError, URLError) as e:
                last_error = e
                if attempt < self.MAX_RETRIES - 1:
                    time.sleep(self.RETRY_BACKOFF * (2**attempt))
                else:
                    logger.warning(f"Request failed for {url} after {self.MAX_RETRIES} attempts: {e}")
            except ValueError:
                # Validation failures are deterministic; never retry.
                raise
        assert last_error is not None
        raise last_error

    @abstractmethod
    def get_emoji(self, emoji: str, /, *, tight: bool = False, margin: int = 1) -> Optional[BytesIO]:
        raise NotImplementedError

    @abstractmethod
    def get_discord_emoji(self, emoji_id: int, /) -> Optional[BytesIO]:
        raise NotImplementedError

    def close(self) -> None:
        """Close the HTTP session."""
        if _has_httpx and hasattr(self, "_httpx_client") and self._httpx_client:
            with suppress(Exception):
                self._httpx_client.close()
        if _has_requests and hasattr(self, "_requests_session") and self._requests_session:
            with suppress(Exception):
                self._requests_session.close()


class DiscordEmojiSourceMixin(HTTPBasedSource):
    """A mixin that adds Discord emoji functionality to another source."""

    BASE_DISCORD_EMOJI_URL: ClassVar[str] = "https://cdn.discordapp.com/emojis/"

    @abstractmethod
    def get_emoji(self, emoji: str, /, *, tight: bool = False, margin: int = 1) -> Optional[BytesIO]:
        raise NotImplementedError

    def get_discord_emoji(self, emoji_id: int, /) -> Optional[BytesIO]:
        """Fetch a Discord custom emoji by snowflake ID as a PNG stream."""
        url = self.BASE_DISCORD_EMOJI_URL + str(emoji_id) + ".png"

        try:
            data = self.request(url)
            return BytesIO(data)
        except Exception as e:
            logger.debug(f"Failed to fetch Discord emoji {emoji_id}: {e}")
            return None


class EmojiCDNSource(DiscordEmojiSourceMixin):
    """A base source that fetches emojis from https://emojicdn.elk.sh/ (using HTTPS)."""

    BASE_EMOJI_CDN_URL: ClassVar[str] = "https://emojicdn.elk.sh/"  # Changed to HTTPS
    STYLE: ClassVar[Optional[str]] = None

    def get_emoji(self, emoji: str, /, *, tight: bool = False, margin: int = 1) -> Optional[BytesIO]:
        """Fetch an emoji PNG stream from EmojiCDN, with optional tight-cropping.

        The method stays small by delegating to helpers for cache and fetch.
        """
        if self.STYLE is None:
            raise TypeError("STYLE class variable unfilled.")

        # Validate emoji input
        if not is_valid_emoji(emoji):
            logger.debug(f"Invalid emoji input: {emoji!r}")
            return None

        # Apply environment defaults
        tight, margin = self._apply_tight_env_defaults(tight, margin)

        # Cache keys (raw and tight variants)
        cache_key = hashlib.md5(f"{emoji}_{self.STYLE}".encode()).hexdigest()
        tight_key = hashlib.md5(f"{emoji}_{self.STYLE}_t{max(0, int(margin))}".encode()).hexdigest()

        # Retry once if this key previously failed
        if self._is_request_failed(cache_key):
            stream = self._fetch_and_persist(emoji, cache_key, tight_key, tight=tight, margin=margin)
            if stream is not None:
                self._clear_failed_request(cache_key)
                return stream

        # Try disk cache
        if self.disk_cache and self._cache_dir:
            stream = self._load_from_cache(cache_key, tight_key, tight=tight, margin=margin)
            if stream is not None:
                return stream

        # Fresh fetch
        stream = self._fetch_and_persist(emoji, cache_key, tight_key, tight=tight, margin=margin)
        if stream is None:
            self._mark_request_failed(cache_key)
        return stream

    # --- Small helpers to keep get_emoji simple ---
    def _apply_tight_env_defaults(self, tight: bool, margin: int) -> tuple[bool, int]:
        if not tight:
            env_tight = os.getenv("PARMOJI_TIGHT", "").strip().lower()
            if env_tight and env_tight not in {"0", "false", "no", "off"}:
                tight = True
        if tight:
            with suppress(ValueError):
                env_margin = os.getenv("PARMOJI_TIGHT_MARGIN", "").strip()
                if env_margin:
                    margin = int(env_margin)
        return tight, margin

    def _load_from_cache(self, cache_key: str, tight_key: str, *, tight: bool, margin: int) -> Optional[BytesIO]:
        assert self._cache_dir is not None
        cache_file = self._cache_dir / f"{cache_key}.png"
        t_cache_file = self._cache_dir / f"{tight_key}.png"

        # If tight variant exists, prefer it
        if tight and t_cache_file.exists():
            try:
                return BytesIO(t_cache_file.read_bytes())
            except Exception as e:  # pragma: no cover - cache I/O edge
                logger.debug(f"Failed to load tight cache: {e}")

        if cache_file.exists():
            try:
                data = cache_file.read_bytes()
                if tight:
                    cropped = self._tight_crop_png_bytes(data, margin)
                    try:
                        t_cache_file.write_bytes(cropped)
                    except Exception as e:  # pragma: no cover - cache I/O edge
                        logger.debug(f"Failed to write derived tight cache: {e}")
                    return BytesIO(cropped)
                return BytesIO(data)
            except Exception as e:  # pragma: no cover - cache I/O edge
                logger.debug(f"Failed to load base cache: {e}")
        return None

    def _fetch_and_persist(
        self, emoji: str, cache_key: str, tight_key: str, *, tight: bool, margin: int
    ) -> Optional[BytesIO]:
        assert self.STYLE is not None
        url = self.BASE_EMOJI_CDN_URL + quote_plus(emoji) + "?style=" + quote_plus(self.STYLE)
        try:
            data = self.request(url)
        except Exception as e:
            logger.debug(f"Fetch failed for {emoji}: {e}")
            return None

        out_bytes = self._tight_crop_png_bytes(data, margin) if tight else data
        stream = BytesIO(out_bytes)

        if self.disk_cache and self._cache_dir:
            try:
                (self._cache_dir / f"{cache_key}.png").write_bytes(data)
                if tight:
                    (self._cache_dir / f"{tight_key}.png").write_bytes(out_bytes)
            except Exception as e:  # pragma: no cover - cache I/O edge
                logger.debug(f"Failed to write cache files: {e}")
        return stream

    # --- Image helpers ---
    @staticmethod
    def _tight_crop_png_bytes(data: bytes, margin: int = 1) -> bytes:
        """Return PNG bytes cropped to the alpha bounding box with margin.

        If the image lacks an alpha channel or the computed bounding box
        matches the full image, returns the original bytes.
        """
        try:
            with Image.open(BytesIO(data)) as im:
                im_rgba = im.convert("RGBA")
                alpha = im_rgba.split()[3]
                bbox = alpha.getbbox()
                if not bbox:
                    # Fully transparent or no content; return original
                    return data

                left, top, right, bottom = bbox
                if margin > 0:
                    left = max(0, left - margin)
                    top = max(0, top - margin)
                    right = min(im_rgba.width, right + margin)
                    bottom = min(im_rgba.height, bottom + margin)

                if left == 0 and top == 0 and right == im_rgba.width and bottom == im_rgba.height:
                    return data

                cropped = im_rgba.crop((left, top, right, bottom))
                out = BytesIO()
                cropped.save(out, format="PNG")
                out.seek(0)
                return out.getvalue()
        except Exception as e:  # pragma: no cover - best-effort; fall back to original
            logger.debug(f"tight-crop failed; returning original bytes: {e}")
            return data


class TwitterEmojiSource(EmojiCDNSource):
    """A source that uses Twitter-style emojis. These are also the ones used in Discord."""

    STYLE = "twitter"


class AppleEmojiSource(EmojiCDNSource):
    """A source that uses Apple emojis."""

    STYLE = "apple"


class GoogleEmojiSource(EmojiCDNSource):
    """A source that uses Google emojis."""

    STYLE = "google"


class MicrosoftEmojiSource(EmojiCDNSource):
    """A source that uses Microsoft emojis."""

    STYLE = "microsoft"


class SamsungEmojiSource(EmojiCDNSource):
    """A source that uses Samsung emojis."""

    STYLE = "samsung"


class WhatsAppEmojiSource(EmojiCDNSource):
    """A source that uses WhatsApp emojis."""

    STYLE = "whatsapp"


class FacebookEmojiSource(EmojiCDNSource):
    """A source that uses Facebook emojis."""

    STYLE = "facebook"


class MessengerEmojiSource(EmojiCDNSource):
    """A source that uses Facebook Messenger's emojis."""

    STYLE = "messenger"


class JoyPixelsEmojiSource(EmojiCDNSource):
    """A source that uses JoyPixels' emojis."""

    STYLE = "joypixels"


class OpenmojiEmojiSource(EmojiCDNSource):
    """A source that uses Openmoji emojis."""

    STYLE = "openmoji"


class EmojidexEmojiSource(EmojiCDNSource):
    """A source that uses Emojidex emojis."""

    STYLE = "emojidex"


class MozillaEmojiSource(EmojiCDNSource):
    """A source that uses Mozilla's emojis."""

    STYLE = "mozilla"


# Aliases
Openmoji = OpenmojiEmojiSource
FacebookMessengerEmojiSource = MessengerEmojiSource
TwemojiEmojiSource = Twemoji = TwitterEmojiSource
