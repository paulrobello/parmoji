# Release Notes

## 2.1.0 — 2026-07-30

Resolves 59 of 60 findings from a full architecture / security / quality / documentation audit. No breaking API changes for correctly-using callers — all new behavior is opt-in via defaulted parameters; defaults are byte-for-byte preserved.

Security
- Harden image fetching against decompression bombs: explicit `Image.MAX_IMAGE_PIXELS` ceiling, 2 MiB response-size cap, and Content-Type validation before `Image.open` (SEC-001).
- `HTTPBasedSource.request()` now enforces an HTTPS + host allowlist on both the request URL and the final redirect (SEC-002).
- New overridable `TRUST_ENV` ClassVar controls httpx proxy-env honoring (SEC-003).
- Conservative major-version upper bounds on security-sensitive dependencies (SEC-004).
- Warning logs no longer echo full URLs or raw exception text (SEC-005).
- Cache-key hash switched from MD5 to blake2b (SEC-006; existing on-disk caches rebuild on first fetch).

Fixed
- **Animated Discord emoji** (`<a:name:id>`) now fetch as `.gif` instead of silently failing as `.png` and being permanently recorded as failed (ARC-002).
- **`Parmoji.open()`** now restores the httpx client after `close()`/`open()` instead of leaving the default backend dead (ARC-003).
- `cache_size <= 1` no longer produces a `maxsize=0` Discord cache (QA-001).
- Concurrent rendering no longer races on a closed `BytesIO` or mutated cache (ARC-007).
- `PIL_VERSION` parse no longer crashes on a Pillow prerelease (e.g. `12.3.0.dev0`).

Changed
- **Dependency contract:** httpx, requests, emoji, and xdg-base-dirs are hard dependencies (they always were). Removed the dead optional-import guards and the unreachable urllib fallback. A new `HTTP_BACKEND` ClassVar selects `httpx` (default) or `requests` (ARC-004).
- **Caches** now store immutable `bytes`; the separate cache lock and close-on-evict are gone, and `_processed_image_cache` is bounded by a third LRU (ARC-006/007).
- **Disk-cache** logic promoted to `BaseSource._cache_get`/`_cache_put` template methods. `LocalFontSource` now honors `tight`/`margin` (previously ignored) and matches the `BaseSource` contract — default output is unchanged, but `tight=True` now crops correctly (ARC-008).
- Single source of truth for `PIL_VERSION`/`HAS_GETLENGTH` and emoji detection in `helpers` (ARC-009).

Added
- **PEP 561 typed package:** `py.typed` ships in the wheel, so downstream type checkers see the real types (ARC-001).
- `stroke_width` parameter on `getsize`/`Parmoji.getsize` for accurate stroked-text measurement (default `0` preserves old behavior).
- `DiscordEmojiSource` as the preferred alias for `DiscordEmojiSourceMixin`.
- `CONTRIBUTING.md`; `LocalFontSource`, all built-in sources, and the `HTTPBasedSource` ClassVars are now documented.

Internal
- Narrowed broad `except Exception` handling across all modules; cache-write failures now log at warning.
- Removed autouse test fixtures that masked renderer failures — the suite now validates real rendering (QA-004).
- Extracted `_FailedRequestCache`, `_get_cached`, and `_coerce_source`; made `LRUCacheDict` generic; replaced the hand-rolled test timeout with `pytest-timeout`.
- `__author__` corrected to `Paul Robello` (jay3332 remains credited as the original Pilmoji author).

## 2.0.8 — 2026-07-30

Changed
- Updated dependencies.
- Ensured Python 3.13 compatibility.

## 2.0.7 — 2025-09-14

Enhancements
- Added tight-cropping for CDN-based emoji sources (e.g., Twemoji) via
  `get_emoji(emoji, *, tight=True, margin=1)`. This removes transparent
  padding so the visible glyph fills the intended cell area, especially helpful
  for multi-cell flags.
- Derived tight-cropped images are cached on disk using a derived key to avoid
  repeated processing.
- Optional environment defaults:
  - `PARMOJI_TIGHT=1` enables tight-cropping by default.
  - `PARMOJI_TIGHT_MARGIN=<int>` sets the default margin.

Notes
- Local font source already renders tightly cropped images; it accepts the new
  parameters for API compatibility but ignores them.
