from __future__ import annotations

from io import BytesIO
from typing import Optional

import pytest

from parmoji.source import HTTPBasedSource


class _TestHTTPSource(HTTPBasedSource):
    """Concrete for exercising HTTPBasedSource internals in isolation."""

    def get_emoji(self, emoji: str):  # pragma: no cover - not used here
        return None

    def get_discord_emoji(self, emoji_id: int):  # pragma: no cover - not used here
        return None


@pytest.mark.parmoji
def test_httpx_request_success_and_close(monkeypatch):
    class _Resp:
        def __init__(self, data: bytes):
            self.content = data

        def raise_for_status(self):
            return None

    closed: dict[str, bool] = {"closed": False}

    class _Client:
        def __init__(self, *a, **k):
            pass

        def get(self, url: str):
            return _Resp(b"PNG\x00test")

        def close(self):
            closed["closed"] = True

    import parmoji.source as src

    class _Timeout:
        def __init__(self, *a, **k):
            pass

    class _Limits:
        def __init__(self, *a, **k):
            pass

    monkeypatch.setattr(
        src,
        "httpx",
        type("_httpx", (), {"Client": _Client, "Timeout": _Timeout, "Limits": _Limits}),
    )
    monkeypatch.setattr(src, "_has_httpx", True, raising=False)

    s = _TestHTTPSource(disk_cache=False)
    data = s.request("https://example")
    assert data.startswith(b"PNG")
    s.close()
    assert closed["closed"] is True


@pytest.mark.parmoji
def test_requests_request_success(monkeypatch):
    # Force requests path: disable httpx
    import parmoji.source as src

    monkeypatch.setattr(src, "_has_httpx", False, raising=False)

    class _Resp:
        def __init__(self, data: bytes):
            self.content = data

        def raise_for_status(self):
            return None

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    class _Session:
        def __init__(self, *a, **k):
            pass

        def get(self, url: str, **kwargs):
            return _Resp(b"PNG\x00req")

        def mount(self, *_a, **_k):
            return None

        def close(self):
            return None

    # Provide Retry and HTTPAdapter stubs
    class _HTTPAdapter:
        def __init__(self, *a, **k):
            pass

    class _Retry:
        def __init__(self, *a, **k):
            pass

    monkeypatch.setattr(src, "requests", type("_Req", (), {"Session": _Session}))
    monkeypatch.setattr(src, "HTTPAdapter", _HTTPAdapter)
    monkeypatch.setattr(src, "Retry", _Retry)
    monkeypatch.setattr(src, "_has_requests", True, raising=False)

    s = _TestHTTPSource(disk_cache=False)
    data = s.request("https://example")
    assert data.startswith(b"PNG\x00req")
    s.close()  # exercise close path for requests client


@pytest.mark.parmoji
def test_urllib_request_success(monkeypatch):
    # Force urllib path: disable httpx and requests
    import parmoji.source as src

    monkeypatch.setattr(src, "_has_httpx", False, raising=False)
    monkeypatch.setattr(src, "_has_requests", False, raising=False)

    class _Resp:
        def __init__(self, data: bytes):
            self._data = data

        def read(self) -> bytes:
            return self._data

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def _urlopen(req, timeout: Optional[float] = None):  # noqa: ARG001
        return _Resp(b"PNG\x00ul")

    monkeypatch.setattr(src, "urlopen", _urlopen)

    s = _TestHTTPSource(disk_cache=False)
    data = s.request("https://example")
    assert data.startswith(b"PNG\x00ul")


@pytest.mark.parmoji
def test_httpx_request_failure_raises(monkeypatch):
    class _Client:
        def __init__(self, *a, **k):
            pass

        def get(self, url: str):
            raise RuntimeError("fail!")

        def close(self):
            return None

    class _Timeout:
        def __init__(self, *a, **k):
            pass

    class _Limits:
        def __init__(self, *a, **k):
            pass

    import parmoji.source as src

    # Speed up retry loop by skipping sleep
    monkeypatch.setattr(src.time, "sleep", lambda *_a, **_k: None)

    monkeypatch.setattr(
        src,
        "httpx",
        type("_httpx", (), {"Client": _Client, "Timeout": _Timeout, "Limits": _Limits}),
    )
    monkeypatch.setattr(src, "_has_httpx", True, raising=False)

    s = _TestHTTPSource(disk_cache=False)
    with pytest.raises(Exception):
        s.request("https://example")


@pytest.mark.parmoji
def test_requests_request_failure_raises(monkeypatch):
    import parmoji.source as src

    monkeypatch.setattr(src, "_has_httpx", False, raising=False)

    class _Session:
        def __init__(self, *a, **k):
            pass

        def mount(self, *a, **k):  # pragma: no cover - setup
            return None

        def get(self, *a, **k):
            raise RuntimeError("nope")

        def close(self):  # pragma: no cover - cleanup
            return None

    class _HTTPAdapter:  # pragma: no cover - setup
        def __init__(self, *a, **k):
            pass

    class _Retry:  # pragma: no cover - setup
        def __init__(self, *a, **k):
            pass

    monkeypatch.setattr(src, "requests", type("_Req", (), {"Session": _Session}))
    monkeypatch.setattr(src, "HTTPAdapter", _HTTPAdapter)
    monkeypatch.setattr(src, "Retry", _Retry)
    monkeypatch.setattr(src, "_has_requests", True, raising=False)

    s = _TestHTTPSource(disk_cache=False)
    with pytest.raises(Exception):
        s.request("https://example")


@pytest.mark.parmoji
def test_urllib_request_failure_raises(monkeypatch):
    import parmoji.source as src

    monkeypatch.setattr(src, "_has_httpx", False, raising=False)
    monkeypatch.setattr(src, "_has_requests", False, raising=False)
    # Avoid sleeping during backoff
    monkeypatch.setattr(src.time, "sleep", lambda *_a, **_k: None)

    def _urlopen_fail(req, timeout=None):  # noqa: ARG001
        raise src.URLError("boom")

    monkeypatch.setattr(src, "urlopen", _urlopen_fail)

    s = _TestHTTPSource(disk_cache=False)
    with pytest.raises(Exception):
        s.request("https://example")


@pytest.mark.parmoji
def test_failed_cache_file_clear(monkeypatch, tmp_path):
    import parmoji.source as src

    # Use requests path but it's irrelevant; we just want disk cache enabled
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / ".cache"))

    # Provide minimal stubs for requests
    monkeypatch.setattr(src, "_has_httpx", False, raising=False)

    class _Session:
        def __init__(self, *a, **k):
            pass

        def mount(self, *_a, **_k):
            return None

        def close(self):
            return None

        def get(self, *a, **k):  # pragma: no cover - not called
            raise RuntimeError

    class _HTTPAdapter:  # pragma: no cover - not exercised
        def __init__(self, *a, **k):
            pass

    class _Retry:  # pragma: no cover - not exercised
        def __init__(self, *a, **k):
            pass

    monkeypatch.setattr(src, "requests", type("_Req", (), {"Session": _Session}))
    monkeypatch.setattr(src, "HTTPAdapter", _HTTPAdapter)
    monkeypatch.setattr(src, "Retry", _Retry)
    monkeypatch.setattr(src, "_has_requests", True, raising=False)

    s = _TestHTTPSource(disk_cache=True)
    # Mark a fake failure (persists to cache file)
    s._mark_request_failed("abc")
    assert s._failed_cache_file is not None and s._failed_cache_file.exists()

    s.clear_failed_cache()
    # Cache file should be gone and set cleared
    assert s._failed_cache_file is not None
    assert not s._failed_cache_file.exists()
    assert not s._failed_requests
