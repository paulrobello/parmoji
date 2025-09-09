from __future__ import annotations

import importlib
import sys
import types

import pytest


@pytest.mark.parmoji
def test_source_imports_without_requests_and_httpx(monkeypatch):
    import builtins

    # Make importing requests and httpx raise ImportError
    real_import = builtins.__import__

    def fake_import(name, *a, **k):  # type: ignore[override]
        if name in ("requests", "httpx"):
            raise ImportError(name)
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    import parmoji.source as src

    # Reload with imports failing
    src2 = importlib.reload(src)
    # Both flags should be False and urllib path used
    assert not getattr(src2, "_has_requests")
    assert not getattr(src2, "_has_httpx")

    # Exercise urllib request path directly with a tiny stub
    def _urlopen_stub(req, timeout=None):  # noqa: ANN001
        class _Resp:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self):
                return b"PNG\x00u"

        return _Resp()

    monkeypatch.setattr(src2, "urlopen", _urlopen_stub)

    # Define a minimal subclass to call request
    class _S(src2.HTTPBasedSource):
        def get_emoji(self, emoji: str):  # pragma: no cover - not used
            return None

        def get_discord_emoji(self, emoji_id: int):  # pragma: no cover - not used
            return None

    s = _S(disk_cache=False)
    data = s.request("https://example")
    assert data.startswith(b"PNG\x00u")
