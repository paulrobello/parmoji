from __future__ import annotations

import importlib

import pytest


@pytest.mark.parmoji
def test_core_resampling_import_fallback(monkeypatch):
    # Remove Resampling before reload to hit fallback lines
    import PIL.Image as PImage

    had = hasattr(PImage, "Resampling")
    saved = getattr(PImage, "Resampling", None)
    if had:
        delattr(PImage, "Resampling")
    try:
        from parmoji import core

        core2 = importlib.reload(core)
        assert getattr(core2, "LANCZOS", None) is not None
    finally:
        if had:
            PImage.Resampling = saved
        from parmoji import core

        importlib.reload(core)
