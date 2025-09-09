from __future__ import annotations

import platform as _platform

import pytest

from parmoji.local_source import LocalFontSource


@pytest.mark.parmoji
def test_local_source_init_windows(monkeypatch):
    monkeypatch.setattr(_platform, "system", lambda: "Windows")
    # Should not raise and should fallback to default if fonts not present
    src = LocalFontSource(disk_cache=False, prime_on_init=False)
    assert src.emoji_font is not None


@pytest.mark.parmoji
def test_local_source_init_linux(monkeypatch):
    monkeypatch.setattr(_platform, "system", lambda: "Linux")
    src = LocalFontSource(disk_cache=False, prime_on_init=False)
    assert src.emoji_font is not None
