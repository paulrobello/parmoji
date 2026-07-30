from __future__ import annotations

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
    # ARC-004: httpx is the default backend (HTTP_BACKEND == "httpx"); no
    # module-level flag to toggle.
    class _Resp:
        def __init__(self, data: bytes):
            self.content = data
            self.headers = {
                "Content-Type": "image/png",
                "Content-Length": str(len(data)),
            }
            self.url = "https://emojicdn.elk.sh/"

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

    s = _TestHTTPSource(disk_cache=False)
    data = s.request("https://emojicdn.elk.sh/dummy")
    assert data.startswith(b"PNG")
    s.close()
    assert closed["closed"] is True


@pytest.mark.parmoji
def test_requests_request_success(monkeypatch):
    # ARC-004: select the requests backend via HTTP_BACKEND instead of the
    # removed _has_httpx / _has_requests flags.
    import parmoji.source as src

    class _Resp:
        def __init__(self, data: bytes):
            self.content = data
            self.headers = {
                "Content-Type": "image/png",
                "Content-Length": str(len(data)),
            }
            self.url = "https://emojicdn.elk.sh/"

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

    class _HTTPAdapter:
        def __init__(self, *a, **k):
            pass

    class _Retry:
        def __init__(self, *a, **k):
            pass

    monkeypatch.setattr(src, "requests", type("_Req", (), {"Session": _Session}))
    monkeypatch.setattr(src, "HTTPAdapter", _HTTPAdapter)
    monkeypatch.setattr(src, "Retry", _Retry)

    class _RequestsSrc(_TestHTTPSource):
        HTTP_BACKEND = "requests"

    s = _RequestsSrc(disk_cache=False)
    data = s.request("https://emojicdn.elk.sh/dummy")
    assert data.startswith(b"PNG\x00req")
    s.close()  # exercise close path for requests client


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

    s = _TestHTTPSource(disk_cache=False)
    with pytest.raises(Exception):
        s.request("https://emojicdn.elk.sh/dummy")


@pytest.mark.parmoji
def test_requests_request_failure_raises(monkeypatch):
    import parmoji.source as src

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

    class _RequestsSrc(_TestHTTPSource):
        HTTP_BACKEND = "requests"

    s = _RequestsSrc(disk_cache=False)
    with pytest.raises(Exception):
        s.request("https://emojicdn.elk.sh/dummy")


@pytest.mark.parmoji
def test_request_raises_when_no_backend_configured(monkeypatch):
    # ARC-004: with neither client set, request() raises RuntimeError instead
    # of falling through to a urllib backend (which is gone).
    s = _TestHTTPSource(disk_cache=False)
    s._httpx_client = None
    s._requests_session = None
    with pytest.raises(RuntimeError):
        s.request("https://emojicdn.elk.sh/dummy")


@pytest.mark.parmoji
def test_failed_cache_file_clear(monkeypatch, tmp_path):
    # ARC-004: no backend forcing needed — the test never makes a request, so
    # the default httpx backend is fine and no network call is made.
    import parmoji.source as src

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / ".cache"))

    s = _TestHTTPSource(disk_cache=True)
    # Mark a fake failure (persists to cache file)
    s._mark_request_failed("abc")
    assert s._failed_cache_file is not None and s._failed_cache_file.exists()

    s.clear_failed_cache()
    # Cache file should be gone and set cleared
    assert s._failed_cache_file is not None
    assert not s._failed_cache_file.exists()
    assert not s._failed_requests


@pytest.mark.parmoji
def test_http_backend_classvar_selects_requests(monkeypatch):
    # ARC-004: HTTP_BACKEND drives which client gets built in __init__.
    import parmoji.source as src

    class _Session:
        def __init__(self, *a, **k):
            pass

        def mount(self, *_a, **_k):
            return None

        def close(self):  # pragma: no cover
            return None

    class _HTTPAdapter:  # pragma: no cover
        def __init__(self, *a, **k):
            pass

    class _Retry:  # pragma: no cover
        def __init__(self, *a, **k):
            pass

    monkeypatch.setattr(src, "requests", type("_Req", (), {"Session": _Session}))
    monkeypatch.setattr(src, "HTTPAdapter", _HTTPAdapter)
    monkeypatch.setattr(src, "Retry", _Retry)

    class _RequestsSrc(_TestHTTPSource):
        HTTP_BACKEND = "requests"

    s_http = _TestHTTPSource(disk_cache=False)
    s_req = _RequestsSrc(disk_cache=False)
    assert s_http._httpx_client is not None and s_http._requests_session is None
    assert s_req._httpx_client is None and s_req._requests_session is not None
