# Parmoji

[![PyPI](https://img.shields.io/pypi/v/parmoji)](https://pypi.org/project/parmoji/)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/parmoji.svg)](https://pypi.org/project/parmoji/)
![Runs on Linux | macOS | Windows](https://img.shields.io/badge/runs%20on-Linux%20%7C%20macOS%20%7C%20Windows-blue)
![Arch x86-64 | ARM | AppleSilicon](https://img.shields.io/badge/arch-x86--64%20%7C%20ARM%20%7C%20AppleSilicon-blue)
![PyPI - Downloads](https://img.shields.io/pypi/dm/parmoji)
![PyPI - License](https://img.shields.io/pypi/l/parmoji)

[![Build](https://github.com/paulrobello/parmoji/actions/workflows/build.yml/badge.svg)](https://github.com/paulrobello/parmoji/actions/workflows/build.yml)
[![codecov](https://codecov.io/gh/paulrobello/parmoji/branch/main/graph/badge.svg)](https://codecov.io/gh/paulrobello/parmoji)
[![Release](https://github.com/paulrobello/parmoji/actions/workflows/release.yml/badge.svg)](https://github.com/paulrobello/parmoji/actions/workflows/release.yml)
[![Publish (PyPI)](https://github.com/paulrobello/parmoji/actions/workflows/publish.yml/badge.svg)](https://github.com/paulrobello/parmoji/actions/workflows/publish.yml)
[![Publish (TestPyPI)](https://github.com/paulrobello/parmoji/actions/workflows/publish-dev.yml/badge.svg)](https://github.com/paulrobello/parmoji/actions/workflows/publish-dev.yml)
[![TestPyPI](https://img.shields.io/badge/TestPyPI-parmoji-orange)](https://test.pypi.org/project/parmoji/)

## Description
Parmoji is a Pillow-based emoji rendering library (unicode + Discord custom emoji) with pluggable image sources
(HTTP CDN and local font), LRU in-memory caching, and optional on-disk caching using XDG locations. It’s extracted
from the par-term-emu project and packaged as a standalone library for reuse.

[![Buy Me A Coffee](https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png)](https://buymeacoffee.com/probello3)

## Technology
- Python 3.11+
- Pillow
- httpx (primary HTTP backend) and requests (selectable alternate backend)

## Prerequisites
- Python 3.11 or higher
- uv package manager (recommended)

## Features
- Unicode and Discord emoji
- Multi-line rendering with alignment and anchors
- Fine control over emoji size/position per draw call
- Multiple built-in emoji sources (Twemoji, Apple, Google, etc.)
- LRU in-memory cache and optional disk cache (XDG)
- PEP 561 typed (`py.typed` ships; inline types are visible to pyright/mypy)
- Selectable HTTP backend (httpx default; switch to `requests` per source via `HTTP_BACKEND`)

## Installation
```shell
uv add parmoji
```

## Update
```shell
uv add parmoji -U
```

## Quickstart
```python
from parmoji import Parmoji
from parmoji.source import TwitterEmojiSource
from PIL import Image, ImageFont

text = "Hello 👋  from Parmoji 😎"

img = Image.new("RGBA", (480, 120), (255, 255, 255, 255))
font = ImageFont.load_default()

with Parmoji(img, source=TwitterEmojiSource, cache=True) as p:
    p.text((10, 20), text, fill=(0, 0, 0), font=font)

img.save("parmoji_example.png")
```

## Emoji Sources and Caching
- Default source is `Twemoji` (Twitter-style). Swap via `Parmoji(image, source=AppleEmojiSource)`.
- Disk cache: construct sources with `disk_cache=True` to persist assets.
- Cache location: `$XDG_CACHE_HOME/par-term/parmoji/<SourceClass>/` (or `~/.cache/par-term/parmoji/<SourceClass>/`).
- Clear failed CDN retries: `source.clear_failed_cache()`.

### Built-in sources
Parmoji ships twelve HTTP CDN styles (all routed through `https://emojicdn.elk.sh/`) plus one offline source. CDN sources are imported from `parmoji.source`; the offline source from `parmoji.local_source`.

| Class | `STYLE` |
| --- | --- |
| `TwitterEmojiSource` | `twitter` |
| `AppleEmojiSource` | `apple` |
| `GoogleEmojiSource` | `google` |
| `MicrosoftEmojiSource` | `microsoft` |
| `SamsungEmojiSource` | `samsung` |
| `WhatsAppEmojiSource` | `whatsapp` |
| `FacebookEmojiSource` | `facebook` |
| `MessengerEmojiSource` | `messenger` |
| `JoyPixelsEmojiSource` | `joypixels` |
| `OpenmojiEmojiSource` | `openmoji` |
| `EmojidexEmojiSource` | `emojidex` |
| `MozillaEmojiSource` | `mozilla` |
| `LocalFontSource` | _(renders from system fonts; no network)_ |

Aliases: `Twemoji` and `TwemojiEmojiSource` are `TwitterEmojiSource`; `Openmoji` is `OpenmojiEmojiSource`; `FacebookMessengerEmojiSource` is `MessengerEmojiSource`; `DiscordEmojiSource` is the preferred public name for `DiscordEmojiSourceMixin` (every CDN style above already subclasses it, so Discord custom-emoji support is built in). `TwitterEmojiSource` is also the emoji set Discord uses.

### Local font source (offline rendering)
For no-network or system-font rendering, use `LocalFontSource`. It renders emoji from locally installed fonts (Apple Color Emoji on macOS, Segoe UI Emoji on Windows, Noto Color Emoji on Linux by default) and needs no HTTP backend. It supports the same `disk_cache` and `get_emoji(..., tight=, margin=)` API as the CDN sources.

```python
from parmoji.local_source import LocalFontSource

src = LocalFontSource(disk_cache=True)  # renders using a detected system emoji font
```

- `get_emoji` always crops to the glyph's alpha bounding box (there is no CDN safe-zone to remove); `tight`/`margin` drive the crop padding and are honored, with results cached under a derived key.
- Discord custom emoji are **not** supported by `LocalFontSource`: `get_discord_emoji(...)` always returns `None`. Use a CDN source if you need Discord emoji.
- Disk-cache I/O is shared with the CDN sources via `BaseSource._cache_get`/`_cache_put`, so cache behavior is consistent across source kinds.

### Tight Cropping (remove Twemoji safe-zone)
Some emoji sets (notably Twemoji) include transparent padding around glyphs. To have the visible emoji fill the cell
area (useful for multi-cell flags), request a tightly cropped asset directly from the source:

```python
from parmoji.source import TwitterEmojiSource

src = TwitterEmojiSource(disk_cache=True)
stream = src.get_emoji("🇺🇸", tight=True, margin=1)  # crop to alpha bbox + 1px margin
```

- Cropped variants are cached on disk with a derived key, so subsequent calls don’t repeat work.
- You can enable tight cropping by default via environment:
  - `PARMOJI_TIGHT=1` to enable
  - `PARMOJI_TIGHT_MARGIN=2` to set a default margin

### Tuning HTTP behavior
`httpx` is the default backend for every CDN source; `requests` is an alternate, selected per subclass via the `HTTP_BACKEND` ClassVar. Both are hard dependencies (no `urllib` fallback).

```python
from parmoji.source import TwitterEmojiSource

class RequestsTwemoji(TwitterEmojiSource):
    HTTP_BACKEND = "requests"
    TIMEOUT = 5.0           # per-request timeout (seconds)
    MAX_RETRIES = 5         # attempt count
    RETRY_BACKOFF = 0.5     # base for exponential backoff
```

The full set of public override knobs lives on `HTTPBasedSource`: `REQUEST_KWARGS`, `TIMEOUT`, `MAX_RETRIES`, `RETRY_BACKOFF`, `HTTP_BACKEND`, `MAX_RESPONSE_BYTES`, `ALLOWED_SCHEMES`, `ALLOWED_HOSTS`, and `TRUST_ENV`. The last three are security guards — `ALLOWED_HOSTS` is re-checked against the post-redirect URL, and any mirror/failover host you point a subclass at must be added there.


## Architecture
For a high-level system design, components, rendering flow, and caching details, see the Architecture overview:

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)

## Development
```shell
make setup          # uv lock + uv sync
make checkall       # lint + format + typecheck + test
make test           # run tests
make package-all    # build wheel + sdist
```

- Pre-commit: `pre-commit install` (then `pre-commit run --all-files`)
- Type checking: `uv run pyright`
- Lint/format: `uv run ruff check --fix src/ tests` and `uv run ruff format src/ tests`

## CI / Releases
- Build & test on push: `.github/workflows/build.yml`
- Publish to TestPyPI (manual): `.github/workflows/publish-dev.yml`
- Publish to PyPI (manual): `.github/workflows/publish.yml` (trusted publishing)
- GitHub Release (manual): `.github/workflows/release.yml`

## Limitations / Known Issues
- **Discord custom emoji require network access.** Discord emoji are fetched from `cdn.discordapp.com` via an HTTP source; `LocalFontSource.get_discord_emoji(...)` always returns `None`.
- **Tight cropping exists to remove CDN safe-zone padding.** Some sets (notably Twemoji) ship glyphs with transparent padding; `get_emoji(..., tight=True, margin=N)` trims to the alpha bounding box so the visible glyph fills its cell (useful for multi-cell flags). `LocalFontSource` already renders tightly cropped and uses `tight`/`margin` only for crop padding.
- **Thread safety.** A single `Parmoji` instance is not safe for concurrent `text()` calls across threads. Create one instance per thread, or serialize access.
- **Single upstream CDN, no automatic failover.** All twelve built-in styles route through one host (`emojicdn.elk.sh`); a host outage takes down every style. Subclass `EmojiCDNSource` with a custom `BASE_EMOJI_CDN_URL` (and add the host to `HTTPBasedSource.ALLOWED_HOSTS`) to point at a mirror.

## What's New
For the full versioned changelog, see [docs/RELEASE_NOTES.md](docs/RELEASE_NOTES.md).

- 2.1.0 — Audit remediation: PEP 561 `py.typed` shipped; animated Discord emoji (`.gif`) and `Parmoji.open()` httpx-restore fixes; HTTP-backend hardening (decompression-bomb guards, host allowlist); bounded, thread-safe `bytes` caches; configurable `HTTP_BACKEND`; `stroke_width`-aware `getsize`; `DiscordEmojiSource` alias.
- 2.0.8 — Updated dependencies and ensure Python 3.13 compatibility
- 2.0.7 — Tight-cropping support for CDN sources (Twemoji, etc.):
  - `get_emoji(..., tight=True, margin=1)` trims Twemoji's transparent safe‑zone.
  - Cropped variants are cached with a derived key.
  - Env toggles: `PARMOJI_TIGHT=1`, `PARMOJI_TIGHT_MARGIN=2`.

## License
MIT — see `LICENSE`.

## Acknowledgements
Originally based on the Pilmoji project by jay3332; heavily refactored and optimized.
