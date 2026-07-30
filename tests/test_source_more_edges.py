from __future__ import annotations

import importlib
from io import BytesIO
from pathlib import Path

import httpx
import pytest
from PIL import Image

import parmoji.source as src


def _png_bytes() -> bytes:
    buf = BytesIO()
    Image.new("RGBA", (4, 4), (255, 0, 0, 255)).save(buf, format="PNG")
    return buf.getvalue()


@pytest.mark.parmoji
def test_basesource_cache_dir_fallback_when_xdg_raises(monkeypatch, tmp_path):
    # Make xdg_cache_home exist and raise to hit except branch
    def _xdg_raise():  # noqa: ANN001
        raise RuntimeError("boom")

    monkeypatch.setattr(src, "xdg_cache_home", _xdg_raise, raising=False)

    class _S(src.BaseSource):
        def get_emoji(self, emoji: str):  # pragma: no cover - not used
            return None

        def get_discord_emoji(self, emoji_id: int):  # pragma: no cover - not used
            return None

    s = _S(disk_cache=True)
    # Should still have a cache dir under HOME/.cache
    assert s._cache_dir is not None and s._cache_dir.exists()


@pytest.mark.parmoji
def test_basesource_notimplemented_methods():
    # Call abstract base implementations directly via __new__ to avoid ABC instantiation
    with pytest.raises(NotImplementedError):
        src.BaseSource.get_emoji(object(), "😀")  # type: ignore[arg-type, abstract]
    with pytest.raises(NotImplementedError):
        src.BaseSource.get_discord_emoji(object(), 1)  # type: ignore[arg-type, abstract]


@pytest.mark.parmoji
def test_mixin_notimplemented_get_emoji():
    # Call abstract mixin method directly; it unconditionally raises
    with pytest.raises(NotImplementedError):
        src.DiscordEmojiSourceMixin.get_emoji(object(), "😀")  # type: ignore[arg-type]


@pytest.mark.parmoji
def test_httpbased_del_suppresses_close_errors(monkeypatch):
    # ARC-004: __del__ now dispatches on client presence, not _has_* flags.

    class _C:
        def close(self):
            raise RuntimeError("boom")

    class _S(src.HTTPBasedSource):
        def __init__(self):  # no disk cache
            # Bypass parent init to avoid opening real clients
            src.BaseSource.__init__(self, disk_cache=False)
            self._httpx_client = _C()  # type: ignore[assignment]
            self._requests_session = _C()  # type: ignore[assignment]

        def get_emoji(self, emoji: str):  # pragma: no cover - not used
            return None

        def get_discord_emoji(self, emoji_id: int):  # pragma: no cover - not used
            return None

    s = _S()
    # Explicit destructor call should suppress close exceptions
    s.__del__()


@pytest.mark.parmoji
def test_httpbased_clear_failed_cache_unlinks_file(monkeypatch, tmp_path):
    # Create instance with disk cache enabled
    class _S(src.HTTPBasedSource):
        def get_emoji(self, emoji: str):  # pragma: no cover - not used
            return None

        def get_discord_emoji(self, emoji_id: int):  # pragma: no cover - not used
            return None

    s = _S(disk_cache=True)
    # Synthesize a failed cache file
    assert s._cache_dir is not None
    s._failed_cache_file = s._cache_dir / "failed_requests.json"
    s._failed_cache_file.write_text('{"failed":["abc"]}')
    s.clear_failed_cache()
    assert not s._failed_cache_file.exists()


@pytest.mark.parmoji
def test_httpbased_failed_cache_mark_and_clear_branches(tmp_path):
    class _S(src.HTTPBasedSource):
        def get_emoji(self, emoji: str):  # pragma: no cover - not used
            return None

        def get_discord_emoji(self, emoji_id: int):  # pragma: no cover - not used
            return None

    s = _S(disk_cache=True)
    # Ensure file path exists
    assert s._cache_dir is not None
    s._failed_cache_file = s._cache_dir / "failed_requests.json"
    # Mark a key -> should write file
    s._mark_request_failed("abc")
    assert s._failed_cache_file.exists()
    # Clear a non-existent key -> exit branch of if
    s._clear_failed_request("not-present")
    # Now clear the existing key -> persist branch
    s._clear_failed_request("abc")
    # Call clear_failed_cache when file already removed => exit branch of exists()
    s.clear_failed_cache()


@pytest.mark.parmoji
def test_httpbased_init_reads_failed_cache_with_invalid_json(tmp_path):
    class _S(src.HTTPBasedSource):
        def get_emoji(self, emoji: str):  # pragma: no cover - not used
            return None

        def get_discord_emoji(self, emoji_id: int):  # pragma: no cover - not used
            return None

    # Prepare a bad JSON failed_requests file under a temp HOME cache
    s1 = _S(disk_cache=True)
    assert s1._cache_dir is not None
    bad = s1._cache_dir / "failed_requests.json"
    bad.write_text("not-json")
    # New instance should hit the loader except branch
    s2 = _S(disk_cache=True)
    assert isinstance(s2._failed_requests, set)


@pytest.mark.parmoji
def test_emojicdn_retry_then_normal_success():
    class _SeqCDN(src.TwitterEmojiSource):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            self.calls = 0

        def request(self, url: str) -> bytes:  # type: ignore[override]
            self.calls += 1
            if self.calls == 1:
                # QA-003: realistic transport error (caught by the narrowed
                # fetch except). Was RuntimeError, which is not a real request()
                # failure and would now propagate.
                raise httpx.HTTPError("first attempt fails")
            # QA-011: real image bytes so the disk-persist validation passes.
            return _png_bytes()

    s = _SeqCDN(disk_cache=True)
    # Set failed to trigger retry branch (which will fail), then normal path
    key = "😀"
    import hashlib

    cache_key = hashlib.blake2b(f"{key}_{s.STYLE}".encode(), digest_size=16).hexdigest()
    s._mark_request_failed(cache_key)
    st = s.get_emoji(key)
    from io import BytesIO

    assert isinstance(st, BytesIO)


@pytest.mark.parmoji
def test_httpbased_notimplemented_proxies():
    with pytest.raises(NotImplementedError):
        src.HTTPBasedSource.get_emoji(object(), "😀")  # type: ignore[arg-type, abstract]
    with pytest.raises(NotImplementedError):
        src.HTTPBasedSource.get_discord_emoji(object(), 1)  # type: ignore[arg-type, abstract]


@pytest.mark.parmoji
def test_prime_cache_logs_exceptions(monkeypatch):
    class _S(src.BaseSource):
        def get_emoji(self, emoji: str):  # noqa: ARG002
            raise RuntimeError("fail")

        def get_discord_emoji(self, emoji_id: int):  # pragma: no cover - not used
            return None

    s = _S(disk_cache=True)
    s.prime_cache({"😀"})  # should catch and log exceptions and continue
