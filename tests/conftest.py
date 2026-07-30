from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _tmp_home_env(monkeypatch, tmp_path_factory):
    """Force HOME into the repo-local .tmp directory for any disk caches.

    Parmoji sources write caches under Path.home()/.cache; the repository IO
    policy requires writes to stay within the workspace. This fixture ensures
    tests never write outside the repo by pointing HOME to a temp directory
    under .tmp/.
    """
    # Place HOME under repo/.tmp to persist across xdist workers if used
    # In this repository the root is one level up from tests/
    repo_root = Path(__file__).resolve().parents[1]
    # Use a session-unique HOME under repo/.tmp derived from pytest's base temp name
    session_id = tmp_path_factory.getbasetemp().name
    tmp_home = repo_root / ".tmp" / f"test-home-parmoji-{session_id}"
    tmp_home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HOME", str(tmp_home))
    # Also ensure XDG_CACHE_HOME follows HOME to keep paths tidy
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_home / ".cache"))
    # Clear any prior parmoji caches for clean test behavior
    cache_root = tmp_home / ".cache" / "par-term" / "parmoji"
    if cache_root.exists():
        import shutil

        shutil.rmtree(cache_root, ignore_errors=True)
    cache_root.mkdir(parents=True, exist_ok=True)
    yield


def pytest_configure(config):
    # Register custom marker to filter parmoji tests: -m parmoji
    config.addinivalue_line("markers", "parmoji: marks tests that target the parmoji subsystem")


@pytest.fixture
def stub_emoji_source():
    """Opt-in BaseSource that returns real PNG streams for every emoji (QA-004).

    Replaces the former autouse fixtures (_ensure_local_source_png and
    _ensure_processed_cache_for_emoji) which unconditionally monkeypatched
    LocalFontSource.get_emoji and Parmoji.text/__exit__ to inject synthetic
    state. Those masked renderer failures (CI sandboxes without color-emoji
    fonts reported green while the real renderer returned nothing) and seeded
    _processed_image_cache with fixture-built images that tests then asserted
    on instead of production behavior.

    Tests that need deterministic emoji rendering — especially on CI where
    LocalFontSource may render a blank image — request this fixture and pass it
    as ``Parmoji(source=stub_emoji_source, ...)``. The returned PNGs are real
    bytes that flow through the true _get_emoji / _build_lines /
    _paste_emoji_for_line path, so cache and paste assertions reflect actual
    behavior. Per-test opt-in keeps every other test honest about real
    rendering.
    """
    from io import BytesIO

    from PIL import Image

    from parmoji.source import BaseSource

    class _StubPngSource(BaseSource):
        def get_emoji(self, emoji: str, /, *, tight: bool = False, margin: int = 1):  # type: ignore[override]
            buf = BytesIO()
            Image.new("RGBA", (16, 16), (255, 255, 255, 255)).save(buf, format="PNG")
            buf.seek(0)
            return buf

        def get_discord_emoji(self, emoji_id: int, /, *, animated: bool = False):  # type: ignore[override]
            buf = BytesIO()
            Image.new("RGBA", (16, 16), (255, 0, 0, 255)).save(buf, format="PNG")
            buf.seek(0)
            return buf

    return _StubPngSource(disk_cache=False)
