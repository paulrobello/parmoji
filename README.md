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
- httpx / requests (optional fallback)

## Prerequisites
- Python 3.11 or higher
- uv package manager (recommended)

## Features
- Unicode and Discord emoji
- Multi-line rendering with alignment and anchors
- Fine control over emoji size/position per draw call
- Multiple built-in emoji sources (Twemoji, Apple, Google, etc.)
- LRU in-memory cache and optional disk cache (XDG)

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

## Development
```shell
make setup          # uv lock + uv sync
make checkall       # format + lint + typecheck + test
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

## License
MIT — see `LICENSE`.

## Acknowledgements
Originally based on the Pilmoji project by jay3332; heavily refactored and extended for standalone packaging.
