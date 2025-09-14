# Release Notes

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
