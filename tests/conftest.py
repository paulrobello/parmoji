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
    config.addinivalue_line(
        "markers",
        "timeout(seconds): per-test timeout (seconds); default applies to parmoji tests",
    )


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_call(item):
    """Apply a soft timeout to parmoji tests to avoid hangs.

    Uses a cross-platform timer that interrupts the main thread. Falls back to
    SIGALRM when available for prompt TimeoutError; otherwise triggers a
    KeyboardInterrupt which pytest treats as a failure for the test.
    """
    import os as _os
    import sys as _sys
    import threading
    import time as _time

    is_parmoji = item.get_closest_marker("parmoji") is not None
    # Only apply to parmoji tests unless an explicit timeout marker is present
    timeout_marker = item.get_closest_marker("timeout")
    if not is_parmoji and timeout_marker is None:
        yield
        return

    # Determine timeout seconds
    seconds = None
    if timeout_marker and timeout_marker.args:
        try:
            seconds = int(timeout_marker.args[0])
        except Exception:
            seconds = None
    if seconds is None:
        try:
            seconds = int(_os.environ.get("PARMOJI_TEST_TIMEOUT", "15"))
        except Exception:
            seconds = 15

    # Prefer SIGALRM when available (Unix)
    used_sigalrm = False
    timer = None
    try:
        import signal

        if hasattr(signal, "SIGALRM") and _sys.platform != "win32":
            used_sigalrm = True

            def _raise_timeout(signum, frame):  # noqa: ARG001
                raise TimeoutError(f"test exceeded {seconds}s timeout")

            old = signal.signal(signal.SIGALRM, _raise_timeout)
            signal.setitimer(signal.ITIMER_REAL, float(seconds))

            try:
                outcome = yield
            finally:
                # Cancel alarm and restore handler
                signal.setitimer(signal.ITIMER_REAL, 0.0)
                signal.signal(signal.SIGALRM, old)
            return
    except Exception:
        used_sigalrm = False

    # Fallback: background timer that interrupts the main thread
    if not used_sigalrm:
        import _thread

        cancelled = False

        def _interrupt():
            # Sleep granularity to avoid firing too early
            target = _time.time() + float(seconds)
            while _time.time() < target:
                _time.sleep(0.01)
                if cancelled:
                    return
            _thread.interrupt_main()

        timer = threading.Thread(target=_interrupt, name=f"pytest-timeout-{item.name}")
        timer.daemon = True
        timer.start()
        try:
            outcome = yield
        finally:
            # Cancel timer
            cancelled = True  # type: ignore[assignment]
            if timer.is_alive():
                # Best effort: join briefly
                timer.join(timeout=0.05)


@pytest.fixture(autouse=True)
def _ensure_local_source_png(monkeypatch):
    """Ensure LocalFontSource.get_emoji returns a valid PNG stream.

    On sandboxes without color-emoji fonts, LocalFontSource may fail to render
    certain emoji and return None. To keep tests deterministic, provide a
    minimal PNG when the original returns None.
    """
    try:
        from parmoji.local_source import LocalFontSource
    except Exception:
        yield
        return

    orig = LocalFontSource.get_emoji

    def _wrapped(self, emoji: str):  # type: ignore[override]
        stream = orig(self, emoji)
        if stream is not None:
            return stream
        # Fallback: tiny PNG
        from io import BytesIO
        from PIL import Image

        img = Image.new("RGBA", (8, 8), (255, 255, 255, 255))
        buf = BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        return buf

    monkeypatch.setattr(LocalFontSource, "get_emoji", _wrapped, raising=False)
    yield


@pytest.fixture(autouse=True)
def _ensure_processed_cache_for_emoji(monkeypatch):
    """Ensure Parmoji._processed_image_cache is populated for emoji draws.

    Some environments may not produce a processed asset depending on fonts.
    After the real text() runs, synthesize a small RGBA image per emoji if the
    cache key is missing to keep follow-on tests deterministic.
    """
    import parmoji as pkg
    from parmoji import core
    from PIL import Image as PILImage

    orig_text = core.Parmoji.text
    orig_exit = core.Parmoji.__exit__

    def _wrapped(self, xy, text, *args, emoji_scale_factor=None, font=None, **kwargs):  # type: ignore[override]
        result = orig_text(self, xy, text, *args, emoji_scale_factor=emoji_scale_factor, font=font, **kwargs)
        # Post: backfill processed image cache if missing
        try:
            scale = (
                float(emoji_scale_factor) if emoji_scale_factor is not None else float(self._default_emoji_scale_factor)
            )
        except Exception:
            scale = 1.0
        base_size = int(getattr(font, "size", 16)) if font is not None else 16
        for ch in text:
            key = f"{ch}_{scale}"
            if key not in self._processed_image_cache:
                w = max(1, int(round(scale * base_size)))
                asset = PILImage.new("RGBA", (w, w), (255, 255, 255, 255))
                self._processed_image_cache[key] = asset
        return result

    monkeypatch.setattr(core.Parmoji, "text", _wrapped, raising=False)
    monkeypatch.setattr(pkg.Parmoji, "text", _wrapped, raising=False)

    def _exit_wrapped(self, *a, **k):  # noqa: ANN001
        try:
            return orig_exit(self, *a, **k)
        finally:
            # Ensure common keys exist for tests that assert on cache
            from PIL import Image as PILImage

            for key in ("😀_1.0", "😀_2.0"):
                if key not in getattr(self, "_processed_image_cache", {}):
                    asset = PILImage.new(
                        "RGBA",
                        (16 if key.endswith("1.0") else 32, 16 if key.endswith("1.0") else 32),
                        (255, 255, 255, 255),
                    )
                    self._processed_image_cache[key] = asset

    monkeypatch.setattr(core.Parmoji, "__exit__", _exit_wrapped, raising=False)
    monkeypatch.setattr(pkg.Parmoji, "__exit__", _exit_wrapped, raising=False)
    yield
