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
from typing import AbstractSet, Any, ClassVar, Dict, Final, Optional, Set
from urllib.parse import quote_plus, urlparse

import httpx
import requests
from PIL import Image
from requests.adapters import HTTPAdapter
from urllib3.util import Retry
from xdg_base_dirs import xdg_cache_home

from .helpers import is_emoji

# SEC-001: explicit decompression-bomb ceiling for untrusted CDN bytes.
# Pillow's default (~89 Mpx) is far larger than any emoji needs; tighten to
# 20 Mpx (still well above the largest emoji ~1 Mpx). Only ever tighten the
# host application's setting, never relax it.
_MAX_IMAGE_PIXELS_CEILING: int = 20_000_000
if Image.MAX_IMAGE_PIXELS is None or Image.MAX_IMAGE_PIXELS > _MAX_IMAGE_PIXELS_CEILING:
    Image.MAX_IMAGE_PIXELS = _MAX_IMAGE_PIXELS_CEILING

logger = logging.getLogger(__name__)

__all__ = (
    "BaseSource",
    "HTTPBasedSource",
    "DiscordEmojiSourceMixin",
    "DiscordEmojiSource",
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

# Dingbats that are text-presentation by default; rejected at the fetch layer
# unless a VS-16 (U+FE0F) makes them emoji-presentation.
_DINGBAT_TEXT_SYMBOLS: frozenset[str] = frozenset({"\u2713", "\u2717", "\u2714", "\u2716"})

# ARC-011: default emoji set for BaseSource.prime_cache. Hoisted from a
# ~190-line inline literal that obscured the method body. Frozen so it cannot
# be mutated by prime_cache's iteration.
_DEFAULT_PRIME_EMOJIS: Final[frozenset[str]] = frozenset(
    {
        "\U0000261d\U0000fe0f",
        "\U00002620\U0000fe0f",
        "\U00002639\U0000fe0f",
        "\U0000270a",
        "\U0000270b",
        "\U0000270c\U0000fe0f",
        "\U0000270d\U0000fe0f",
        "\U00002763\U0000fe0f",
        "\U00002764\U0000fe0f",
        "\U0001f440",
        "\U0001f441\U0000fe0f",
        "\U0001f441\U0000fe0f\U0000200d\U0001f5e8\U0000fe0f",
        "\U0001f442",
        "\U0001f443",
        "\U0001f444",
        "\U0001f445",
        "\U0001f446",
        "\U0001f447",
        "\U0001f448",
        "\U0001f449",
        "\U0001f44a",
        "\U0001f44b",
        "\U0001f44c",
        "\U0001f44d",
        "\U0001f44e",
        "\U0001f44f",
        "\U0001f450",
        "\U0001f476",
        "\U0001f479",
        "\U0001f47a",
        "\U0001f47b",
        "\U0001f47d",
        "\U0001f47e",
        "\U0001f47f",
        "\U0001f480",
        "\U0001f485",
        "\U0001f48b",
        "\U0001f48c",
        "\U0001f493",
        "\U0001f494",
        "\U0001f495",
        "\U0001f496",
        "\U0001f497",
        "\U0001f498",
        "\U0001f499",
        "\U0001f49a",
        "\U0001f49b",
        "\U0001f49c",
        "\U0001f49d",
        "\U0001f49e",
        "\U0001f49f",
        "\U0001f4a2",
        "\U0001f4a3",
        "\U0001f4a4",
        "\U0001f4a5",
        "\U0001f4a6",
        "\U0001f4a8",
        "\U0001f4a9",
        "\U0001f4aa",
        "\U0001f4ab",
        "\U0001f4ac",
        "\U0001f4ad",
        "\U0001f4af",
        "\U0001f573\U0000fe0f",
        "\U0001f590\U0000fe0f",
        "\U0001f595",
        "\U0001f596",
        "\U0001f5a4",
        "\U0001f5e8\U0000fe0f",
        "\U0001f5ef\U0000fe0f",
        "\U0001f600",
        "\U0001f601",
        "\U0001f602",
        "\U0001f603",
        "\U0001f604",
        "\U0001f605",
        "\U0001f607",
        "\U0001f608",
        "\U0001f60a",
        "\U0001f60b",
        "\U0001f60c",
        "\U0001f60d",
        "\U0001f60e",
        "\U0001f60f",
        "\U0001f610",
        "\U0001f611",
        "\U0001f612",
        "\U0001f613",
        "\U0001f614",
        "\U0001f615",
        "\U0001f616",
        "\U0001f617",
        "\U0001f618",
        "\U0001f619",
        "\U0001f61a",
        "\U0001f61b",
        "\U0001f61c",
        "\U0001f61d",
        "\U0001f61e",
        "\U0001f61f",
        "\U0001f620",
        "\U0001f621",
        "\U0001f622",
        "\U0001f623",
        "\U0001f624",
        "\U0001f625",
        "\U0001f626",
        "\U0001f627",
        "\U0001f628",
        "\U0001f629",
        "\U0001f62a",
        "\U0001f62b",
        "\U0001f62c",
        "\U0001f62d",
        "\U0001f62e",
        "\U0001f62f",
        "\U0001f630",
        "\U0001f631",
        "\U0001f632",
        "\U0001f633",
        "\U0001f634",
        "\U0001f635",
        "\U0001f636",
        "\U0001f637",
        "\U0001f638",
        "\U0001f639",
        "\U0001f63a",
        "\U0001f63b",
        "\U0001f63c",
        "\U0001f63d",
        "\U0001f63e",
        "\U0001f63f",
        "\U0001f640",
        "\U0001f641",
        "\U0001f642",
        "\U0001f644",
        "\U0001f648",
        "\U0001f649",
        "\U0001f64a",
        "\U0001f64c",
        "\U0001f64f",
        "\U0001f90d",
        "\U0001f90e",
        "\U0001f90f",
        "\U0001f911",
        "\U0001f912",
        "\U0001f913",
        "\U0001f914",
        "\U0001f915",
        "\U0001f916",
        "\U0001f917",
        "\U0001f918",
        "\U0001f919",
        "\U0001f91a",
        "\U0001f91b",
        "\U0001f91c",
        "\U0001f91d",
        "\U0001f91e",
        "\U0001f91f",
        "\U0001f920",
        "\U0001f921",
        "\U0001f922",
        "\U0001f923",
        "\U0001f924",
        "\U0001f925",
        "\U0001f927",
        "\U0001f92a",
        "\U0001f92b",
        "\U0001f92c",
        "\U0001f92d",
        "\U0001f92e",
        "\U0001f92f",
        "\U0001f932",
        "\U0001f933",
        "\U0001f970",
        "\U0001f971",
        "\U0001f97a",
        "\U0001f9b4",
        "\U0001f9b5",
        "\U0001f9b6",
        "\U0001f9b7",
        "\U0001f9bb",
        "\U0001f9be",
        "\U0001f9bf",
        "\U0001f9d0",
        "\U0001f9e0",
        "\U0001f9e1",
        "\U0001fa78",
    }
)


def is_valid_emoji(emoji: str) -> bool:
    """Validate that a string is a fetchable emoji.

    ARC-009: delegates the core emoji detection (emoji-library consult plus
    the Unicode-category fallback) to :func:`parmoji.helpers.is_emoji`, which
    is now the single source of truth. On top of that, the fetch validator
    applies two source-specific constraints the layout detector intentionally
    does not (see ``test_text_presentation_dingbats_not_considered_emoji_for_fetch``):

    - a length cap (``MAX_EMOJI_SEQ_LEN``); and
    - rejection of text-presentation dingbats unless VS-16 is present.

    It also accepts lone variation selectors / ZWJ so sequences built around
    them remain fetchable even when the layout detector treats the lone code
    point as non-emoji.
    """
    if not emoji or len(emoji) > MAX_EMOJI_SEQ_LEN:
        return False
    if "\ufe0f" not in emoji and any(ch in _DINGBAT_TEXT_SYMBOLS for ch in emoji):
        return False
    if is_emoji(emoji):
        return True
    return any(ch in ("\ufe0f", "\ufe0e", "\u200d") or unicodedata.category(ch) == "Mn" for ch in emoji)


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
            except (OSError, RuntimeError):
                # QA-003: xdg_cache_home() raises RuntimeError when HOME is
                # unset (covered by test_basesource_cache_dir_fallback_when_xdg_raises);
                # Path ops raise OSError. Fall back to ~/.cache.
                base_cache = Path.home() / ".cache"
            self._cache_dir = base_cache / "par-term" / "parmoji" / self.__class__.__name__
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            logger.debug(f"{self.__class__.__name__}: Disk cache enabled at {self._cache_dir}")

    # --- Disk-cache template methods (ARC-008) ---
    # Promoted here from EmojiCDNSource / LocalFontSource so subclasses supply
    # only the fetch/render step and share one read/write/clear implementation.
    # Both are no-ops when disk_cache is disabled, and best-effort on I/O
    # errors (a cache miss must never break rendering).

    def _cache_get(self, key: str, *, ext: str = ".png") -> Optional[bytes]:
        """Return cached bytes for ``key`` or ``None`` on miss / disabled cache."""
        if not (self.disk_cache and self._cache_dir):
            return None
        cache_file = self._cache_dir / f"{key}{ext}"
        if not cache_file.exists():
            return None
        try:
            return cache_file.read_bytes()
        except OSError as e:
            logger.debug("%s: cache read failed for %s: %s", self.__class__.__name__, key, e)
            return None

    def _cache_put(self, key: str, data: bytes, *, ext: str = ".png") -> None:
        """Best-effort write of ``data`` to the disk cache; no-op if disabled."""
        if not (self.disk_cache and self._cache_dir):
            return
        cache_file = self._cache_dir / f"{key}{ext}"
        try:
            cache_file.write_bytes(data)
        except OSError as e:
            logger.debug("%s: cache write failed for %s: %s", self.__class__.__name__, key, e)

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
    def get_discord_emoji(self, emoji_id: int, /, *, animated: bool = False) -> Optional[BytesIO]:
        """Retrieves a :class:`io.BytesIO` stream for the image of the given Discord emoji.

        Parameters
        ----------
        emoji_id: int
            The snowflake ID of the Discord emoji.
        animated: bool
            Whether the emoji's source tag was the animated ``<a:...>`` form.
            When True the source should prefer the GIF variant (ARC-002).

        Returns
        -------
        :class:`io.BytesIO`
            A bytes stream of the emoji.
        None
            An image for the emoji could not be found.
        """
        raise NotImplementedError

    def prime_cache(self, emojis: Optional[AbstractSet[str]] = None) -> None:
        """Prime the disk cache with commonly used emojis.

        Args:
            emojis: Collection of emoji strings to prime. If None, uses
                the module-level ``_DEFAULT_PRIME_EMOJIS`` set.
        """
        if not self.disk_cache:
            return

        if emojis is None:
            # ARC-011: default prime set hoisted to a module-level Final
            # frozenset; the body now only iterates it.
            emojis = _DEFAULT_PRIME_EMOJIS

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
            except (OSError, ValueError, RuntimeError) as e:
                # QA-003: realistic per-emoji fetch/render failures. Priming is
                # best-effort over many emojis; one bad key must not abort it.
                logger.debug(f"Failed to prime emoji {emoji}: {e}")

        logger.info(f"{self.__class__.__name__}: Primed {primed_count} emojis to cache")

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} disk_cache={self.disk_cache}>"


class _FailedRequestCache:
    """Persistent set of known-bad request keys (QA-005).

    Extracted from ``HTTPBasedSource``. Holds an in-memory set of keys plus an
    optional on-disk JSON file (``failed_requests.json``) so deterministic
    failures (404s, bad CDN responses) are not re-requested on every run. All
    I/O is best-effort: a read failure degrades to an empty set and a write
    failure is logged at warning level (QA-003) so a full disk / permission
    issue is visible to operators without breaking rendering.
    """

    def __init__(self, cache_file: Optional[Path] = None) -> None:
        self._file: Optional[Path] = cache_file
        self._entries: Set[str] = set()
        if cache_file is not None and cache_file.exists():
            try:
                with open(cache_file, "r") as f:
                    data = json.load(f)
                    self._entries = set(data.get("failed", []))
                    logger.debug(f"Loaded {len(self._entries)} failed requests from cache")
            except (OSError, json.JSONDecodeError, ValueError) as e:
                # QA-003: file-read + JSON-parse failures only.
                logger.debug(f"Failed to load failed requests cache: {e}")
                self._entries = set()

    def __contains__(self, key: str) -> bool:
        return key in self._entries

    def add(self, key: str) -> None:
        """Record a failed key and persist it (best-effort)."""
        self._entries.add(key)
        self._save()

    def discard(self, key: str) -> None:
        """Remove a key and persist only if it was actually present."""
        if key in self._entries:
            self._entries.discard(key)
            self._save()

    def clear(self) -> None:
        """Drop all keys and remove the on-disk file if present."""
        self._entries.clear()
        if self._file is not None and self._file.exists():
            try:
                self._file.unlink()
                logger.info("Cleared failed requests cache")
            except OSError as e:
                # QA-003: unlink failures are filesystem errors.
                logger.debug(f"Failed to delete failed cache file: {e}")

    def _save(self) -> None:
        if self._file is None:
            return
        try:
            with open(self._file, "w") as f:
                json.dump({"failed": list(self._entries)}, f)
        except (OSError, ValueError, TypeError) as e:
            # QA-003: persistent-cache WRITE failure -> warn (not debug) so a
            # full disk / permission issue surfaces instead of silently retrying.
            logger.warning(f"Failed to save failed requests cache: {e}")


class HTTPBasedSource(BaseSource):
    """An HTTP-based source with retry logic, timeouts, and security guards.

    Subclasses (e.g. the ``EmojiCDNSource`` style classes) normally only set
    ``STYLE``/URL ClassVars and inherit the fetch/cache/retry machinery here.
    The following ClassVars are the override points a subclass or integrator
    tunes; each defaults to a safe value.

    Attributes:
        REQUEST_KWARGS: Extra keyword arguments forwarded to the requests
            backend's ``Session.get`` (default headers with a Parmoji user
            agent). The httpx backend builds its own headers in ``__init__``.
        TIMEOUT: Per-request timeout in seconds, applied to both backends.
        MAX_RETRIES: Maximum number of request attempts for the httpx retry
            loop; the requests backend configures the same total via
            ``urllib3.util.Retry``.
        RETRY_BACKOFF: Base backoff in seconds for the httpx retry loop; the
            actual delay is ``RETRY_BACKOFF * 2**attempt`` (exponential).
        HTTP_BACKEND: Which backend to use, ``"httpx"`` (default) or
            ``"requests"``. Override to ``"requests"`` in a subclass to select
            that backend.
        MAX_RESPONSE_BYTES: Hard cap on response body size (2 MiB is generous
            for emoji). Responses exceeding this are rejected before the bytes
            are returned to the caller.
        ALLOWED_SCHEMES: URL schemes the public ``request()`` will fetch;
            defaults to ``{"https"}``.
        ALLOWED_HOSTS: Host allowlist enforced on both the request URL and the
            final (post-redirect) URL. Override together with a subclass's CDN
            base to permit a mirror/failover host.
        TRUST_ENV: Whether the httpx backend honors ``HTTP(S)_PROXY`` /
            ``REQUESTS_CA_BUNDLE`` env vars. Defaults to ``True`` for users
            behind corporate proxies; set to ``False`` on shared/container
            hosts where those vars may be attacker-influenced.
    """

    REQUEST_KWARGS: ClassVar[Dict[str, Any]] = {"headers": {"User-Agent": "Mozilla/5.0 (Parmoji/2.0)"}}

    TIMEOUT: ClassVar[float] = 10.0  # 10 second timeout
    MAX_RETRIES: ClassVar[int] = 3
    RETRY_BACKOFF: ClassVar[float] = 0.3

    # ARC-004: httpx and requests are both hard dependencies (pyproject.toml).
    # Select the backend with this ClassVar instead of the former module-level
    # _has_httpx / _has_requests flags, which were always True and made the
    # requests backend unreachable dead code. Override to "requests" in a
    # subclass to use that backend.
    HTTP_BACKEND: ClassVar[str] = "httpx"

    # SEC-001: hard cap on response body size (2 MiB is generous for emoji).
    MAX_RESPONSE_BYTES: ClassVar[int] = 2 * 1024 * 1024
    # SEC-002: only https requests to these hosts are honoured. The final
    # (post-redirect) destination is re-checked in each backend helper.
    ALLOWED_SCHEMES: ClassVar[frozenset[str]] = frozenset({"https"})
    ALLOWED_HOSTS: ClassVar[frozenset[str]] = frozenset({"emojicdn.elk.sh", "cdn.discordapp.com"})

    # SEC-003: httpx honors HTTP(S)_PROXY / NO_PROXY / REQUESTS_CA_BUNDLE env
    # vars by default (trust_env=True). That is the correct default for users
    # behind corporate proxies, but on shared/container hosts where those vars
    # may be attacker-influenced, emoji traffic can be re-routed/intercepted.
    # Override TRUST_ENV = False in a subclass to opt out (no behavior change
    # at the default).
    TRUST_ENV: ClassVar[bool] = True

    def __init__(self, disk_cache: bool = False) -> None:
        super().__init__(disk_cache)

        # QA-005: the persistent failed-request store is now a composed
        # _FailedRequestCache (load/save/clear live there). The on-disk file is
        # only set when disk caching is enabled.
        failed_file = (self._cache_dir / "failed_requests.json") if (disk_cache and self._cache_dir) else None
        self._failed: _FailedRequestCache = _FailedRequestCache(failed_file)

        # Create the configured HTTP backend (httpx preferred, requests fallback).
        # Extracted into _init_http_client so reopen() can rebuild the same
        # backend without duplicating the selection logic (ARC-003).
        # Declared up-front so __del__ has typed attributes even if it fires
        # mid-construction.
        self._httpx_client: Optional[httpx.Client] = None
        self._requests_session: Optional[requests.Session] = None
        self._init_http_client()

    def _init_http_client(self) -> None:
        """Create the HTTP backend selected by :attr:`HTTP_BACKEND`.

        Sets exactly one of ``self._httpx_client`` / ``self._requests_session``
        (the other to ``None``) so :meth:`request` can dispatch on whichever
        client is non-None. Centralised here so both ``__init__`` and
        :meth:`reopen` build identical state.
        """
        # ARC-004: both httpx and requests are hard deps; the former
        # _has_httpx / _has_requests flags were always True, so the requests
        # branch was unreachable dead code. Selection is now explicit.
        if self.HTTP_BACKEND == "httpx":
            self._httpx_client = httpx.Client(
                timeout=httpx.Timeout(self.TIMEOUT),
                limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
                headers={"User-Agent": "Mozilla/5.0 (Parmoji/2.0)"},
                follow_redirects=True,
                trust_env=self.TRUST_ENV,
            )
            self._requests_session = None
        elif self.HTTP_BACKEND == "requests":
            self._httpx_client = None
            self._requests_session = requests.Session()
            retry_strategy = Retry(
                total=self.MAX_RETRIES,
                backoff_factor=self.RETRY_BACKOFF,
                status_forcelist=[429, 500, 502, 503, 504],
            )
            adapter = HTTPAdapter(max_retries=retry_strategy)
            self._requests_session.mount("http://", adapter)
            self._requests_session.mount("https://", adapter)
        else:
            msg = f"HTTP_BACKEND must be 'httpx' or 'requests', got {self.HTTP_BACKEND!r}"
            raise ValueError(msg)

    def reopen(self) -> None:
        """Recreate the HTTP backend after :meth:`close`.

        ARC-003: previously ``Parmoji.open()`` only rebuilt a ``requests``
        session, leaving the default httpx client closed and dead after a
        close/reopen cycle. Client lifecycle now lives on the source: this
        method releases any stale client via :meth:`close` then builds a fresh
        one with the same selection logic as ``__init__``.
        """
        self.close()
        self._init_http_client()

    def __del__(self) -> None:
        """Clean up session on deletion (guarded backstop; prefer :meth:`close`).

        ARC-013: the context manager (:meth:`close` / ``with``) is the supported
        path. ``__del__`` is only a best-effort backstop that can fire during
        interpreter shutdown or before ``__init__`` finished setting attributes,
        so it delegates to :meth:`close` (which itself getattr-guards every
        attribute it touches) and swallows any error silently.
        """
        with suppress(Exception):
            self.close()

    def _mark_request_failed(self, key: str) -> None:
        """Mark a request as failed and persist it."""
        self._failed.add(key)

    def _is_request_failed(self, key: str) -> bool:
        """Check if a request has previously failed."""
        return key in self._failed

    def _clear_failed_request(self, key: str) -> None:
        """Remove a key from the failed requests cache and persist."""
        self._failed.discard(key)

    def clear_failed_cache(self) -> None:
        """Clear the failed requests cache."""
        self._failed.clear()

    # QA-005: back-compat accessors. The failed-request store now lives in
    # ``self._failed`` (a _FailedRequestCache); these expose the former
    # attribute names so existing tests and subclasses that read or mutate the
    # set / on-disk Path keep working unchanged.
    @property
    def _failed_requests(self) -> Set[str]:
        return self._failed._entries

    @property
    def _failed_cache_file(self) -> Optional[Path]:
        return self._failed._file

    @_failed_cache_file.setter
    def _failed_cache_file(self, value: Optional[Path]) -> None:
        # QA-005: back-compat so tests/subclasses can repoint the on-disk file
        # (the live store is self._failed).
        self._failed._file = value

    def request(self, url: str) -> bytes:
        """Makes a GET request to the given URL with timeout and retry.

        Dispatches to the configured backend (httpx or requests), selected by
        :attr:`HTTP_BACKEND`. ARC-004: the urllib fallback is gone — httpx and
        requests are both hard dependencies.

        SEC-002: the URL scheme and host are validated against
        :attr:`ALLOWED_SCHEMES` / :attr:`ALLOWED_HOSTS` before any network
        I/O, and each backend re-checks the final (post-redirect) URL plus
        the response ``Content-Type`` and size.
        """
        self._validate_url(url, source_label="request URL")
        if self._httpx_client is not None:
            return self._request_httpx(url)
        if self._requests_session is not None:
            return self._request_requests(url)
        msg = "No HTTP backend configured"
        raise RuntimeError(msg)

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

    @staticmethod
    def _safe_url_label(url: str) -> str:
        """Return a log-safe identifier (host + path) for ``url``.

        SEC-005: drops query/fragment/userinfo/port so warning-level logs
        aggregated in shared-log contexts cannot leak the full request URL
        (which carries style params) or internal network topology. Returns the
        input unchanged if it has no parseable host.
        """
        parsed = urlparse(url)
        host = parsed.hostname
        return f"{host}{parsed.path}" if host else url

    def _request_httpx(self, url: str) -> bytes:
        assert self._httpx_client is not None
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
                    logger.warning(
                        f"Request failed for {self._safe_url_label(url)} "
                        f"after {self.MAX_RETRIES} attempts: {type(e).__name__}"
                    )
        assert last_error is not None
        raise last_error

    def _request_requests(self, url: str) -> bytes:
        assert self._requests_session is not None
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
            logger.warning("Request failed for %s: %s", self._safe_url_label(url), type(e).__name__)
            raise

    @abstractmethod
    def get_emoji(self, emoji: str, /, *, tight: bool = False, margin: int = 1) -> Optional[BytesIO]:
        raise NotImplementedError

    @abstractmethod
    def get_discord_emoji(self, emoji_id: int, /, *, animated: bool = False) -> Optional[BytesIO]:
        raise NotImplementedError

    def close(self) -> None:
        """Close the HTTP session."""
        client = getattr(self, "_httpx_client", None)
        if client is not None:
            with suppress(Exception):
                client.close()
        session = getattr(self, "_requests_session", None)
        if session is not None:
            with suppress(Exception):
                session.close()


class DiscordEmojiSourceMixin(HTTPBasedSource):
    """A mixin that adds Discord emoji functionality to another source.

    .. note::
        ``DiscordEmojiSource`` is the preferred name for new code; the class
        keeps the ``DiscordEmojiSourceMixin`` name (which predates the
        ``HTTPBasedSource`` base and is no longer a true mixin in the MRO
        sense) as a deprecated alias. A future release will flip which name is
        canonical.
    """

    BASE_DISCORD_EMOJI_URL: ClassVar[str] = "https://cdn.discordapp.com/emojis/"

    @abstractmethod
    def get_emoji(self, emoji: str, /, *, tight: bool = False, margin: int = 1) -> Optional[BytesIO]:
        raise NotImplementedError

    def get_discord_emoji(self, emoji_id: int, /, *, animated: bool = False) -> Optional[BytesIO]:
        """Fetch a Discord custom emoji by snowflake ID.

        ARC-002: animated Discord emoji (the ``<a:name:id>`` form) are served
        as GIF at ``{id}.gif``; static emoji are PNG. Animated IDs request
        ``.gif`` first and fall back to ``.png`` so a mis-flagged ID still
        renders. Static IDs request ``.png`` (no fallback — a static emoji is
        never served as GIF).
        """
        candidates = ("gif", "png") if animated else ("png",)
        for ext in candidates:
            url = self.BASE_DISCORD_EMOJI_URL + str(emoji_id) + "." + ext
            try:
                return BytesIO(self.request(url))
            except (httpx.HTTPError, requests.RequestException, ValueError) as e:
                # QA-003: request() raises ValueError (URL/response validation)
                # or a backend transport error. Try the next candidate extension.
                logger.debug("Failed to fetch Discord emoji %s.%s: %s", emoji_id, ext, e)
        return None


# Non-breaking alias: DiscordEmojiSource is the preferred public name. The class
# inherits HTTPBasedSource concretely despite the "Mixin" suffix, so the name is
# misleading. The alias starts a deprecation path; DiscordEmojiSourceMixin is
# retained for backwards compatibility and is not removed here.
DiscordEmojiSource = DiscordEmojiSourceMixin


class EmojiCDNSource(DiscordEmojiSourceMixin):
    """A base source that fetches emojis from https://emojicdn.elk.sh/ (using HTTPS).

    This is the common base of every built-in emoji set (Twemoji, Apple, Google,
    …). Subclasses only set :attr:`STYLE`; the fetch/cache/retry machinery is
    inherited unchanged.

    Extensibility — bringing your own CDN or failover (ARC-012)
    -----------------------------------------------------------
    The source hierarchy is intentionally pluggable:

    ``BaseSource`` → ``HTTPBasedSource`` (retry/timeout/security guards)
    → ``DiscordEmojiSourceMixin`` → ``EmojiCDNSource`` → style subclasses.

    Two override points let you redirect emoji fetches without touching any
    other code:

    - :attr:`BASE_EMOJI_CDN_URL` — the upstream host. Override in a subclass to
      point at a mirror, a self-hosted CDN, or a failover host::

          class FailoverTwemoji(EmojiCDNSource):
              STYLE = "twitter"
              BASE_EMOJI_CDN_URL = "https://my-mirror.example.com/emojis/"

      The URL must be HTTPS and (per :attr:`HTTPBasedSource.ALLOWED_HOSTS`) the
      host must be added to that allowlist, otherwise :meth:`request` rejects it.
    - :meth:`get_emoji` / :meth:`HTTPBasedSource.request` — override the method
      directly to implement multi-host failover, a local-only fallback, or a
      completely different transport. :class:`LocalFontSource` shows the
      offline, no-transport path.

    Known limitation
    ----------------
    All twelve built-in styles route through a single upstream host
    (``emojicdn.elk.sh``). A host outage takes down every style simultaneously;
    there is no automatic failover built in. For production use, subclass as
    shown above to add your own failover host or mirror.
    """

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
            logger.debug("Invalid emoji input: %r", emoji)
            return None

        # Apply environment defaults
        tight, margin = self._apply_tight_env_defaults(tight, margin)

        # Cache keys (raw and tight variants)
        # SEC-006: blake2b(digest_size=16) for non-cryptographic cache keys.
        # Produces a 32-char hex key (same length as the former MD5); only the
        # hash values change, which invalidates prior on-disk entries (expected
        # — the cache rebuilds). Used for all CDN cache keys.
        cache_key = hashlib.blake2b(f"{emoji}_{self.STYLE}".encode(), digest_size=16).hexdigest()
        tight_key = hashlib.blake2b(f"{emoji}_{self.STYLE}_t{max(0, int(margin))}".encode(), digest_size=16).hexdigest()

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
        # ARC-008: raw I/O delegated to BaseSource._cache_get/_cache_put; this
        # method now holds only the tight-variant selection logic.
        if tight:
            tight_bytes = self._cache_get(tight_key)
            if tight_bytes is not None:
                return BytesIO(tight_bytes)

        base_bytes = self._cache_get(cache_key)
        if base_bytes is None:
            return None
        if tight:
            # Derive the tight variant from the base and persist it.
            cropped = self._tight_crop_png_bytes(base_bytes, margin)
            self._cache_put(tight_key, cropped)
            return BytesIO(cropped)
        return BytesIO(base_bytes)

    def _fetch_and_persist(
        self, emoji: str, cache_key: str, tight_key: str, *, tight: bool, margin: int
    ) -> Optional[BytesIO]:
        assert self.STYLE is not None
        url = self.BASE_EMOJI_CDN_URL + quote_plus(emoji) + "?style=" + quote_plus(self.STYLE)
        try:
            data = self.request(url)
        except (httpx.HTTPError, requests.RequestException, ValueError) as e:
            # QA-003: request() raises ValueError (URL/response validation) or a
            # backend transport error (httpx.HTTPError / requests.RequestException).
            logger.debug("Fetch failed for %s: %s", emoji, e)
            return None

        # QA-011: validate the fetched bytes are actually an image before
        # persisting. A captive-portal interstitial or HTML error page that
        # still 200s (and slips past the SEC-001 Content-Type check) would
        # otherwise become a permanent "valid" cache entry loaded later as an
        # emoji. On validation failure treat it as a fetch error: mark the key
        # failed and do NOT persist.
        if not self._is_valid_image(data):
            logger.debug("Fetched bytes for %s are not a valid image; not persisting", emoji)
            self._mark_request_failed(cache_key)
            return None

        out_bytes = self._tight_crop_png_bytes(data, margin) if tight else data
        # ARC-008: persist via the BaseSource template methods.
        self._cache_put(cache_key, data)
        if tight:
            self._cache_put(tight_key, out_bytes)
        return BytesIO(out_bytes)

    @staticmethod
    def _is_valid_image(data: bytes) -> bool:
        # QA-011: headers+integrity verify that the bytes are a real image.
        # Image.UnidentifiedImageError is an OSError subclass, so (OSError,
        # ValueError) covers unidentified / corrupt / truncated bytes. verify()
        # leaves the image unusable, so callers that need to decode pass the
        # original bytes through Image.open again (as _tight_crop_png_bytes
        # does). Complements SEC-001's Content-Type check (request backends);
        # this is the disk-persist gate.
        try:
            with Image.open(BytesIO(data)) as im:
                im.verify()
            return True
        except (OSError, ValueError) as e:
            logger.debug("Image validation failed: %s", e)
            return False

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
        except (OSError, ValueError) as e:  # pragma: no cover - best-effort; fall back to original
            # QA-003: Image.open/convert/crop raise OSError (covers
            # UnidentifiedImageError) or ValueError on bad args.
            logger.debug("tight-crop failed; returning original bytes: %s", e)
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
