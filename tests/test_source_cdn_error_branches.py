from __future__ import annotations

import hashlib
from io import BytesIO

import pytest

import parmoji.source as src
from parmoji.source import TwitterEmojiSource


class _SpyCDN(TwitterEmojiSource):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.calls = 0

    def request(self, url: str) -> bytes:  # type: ignore[override]
        self.calls += 1
        return b"\x89PNG\r\n\x1a\n\x00\x00HELLO"


@pytest.mark.parmoji
def test_retry_save_to_cache_error_handled(monkeypatch):
    s = _SpyCDN(disk_cache=True)
    emj = "😀"
    key = hashlib.blake2b(f"{emj}_{s.STYLE}".encode(), digest_size=16).hexdigest()
    s._mark_request_failed(key)

    # Force the file write in retry branch to raise
    import builtins

    orig_open = builtins.open

    def _open_err(path, mode="r", *a, **k):  # noqa: ANN001
        if str(path).endswith(f"{key}.png") and "w" in mode:
            raise OSError("disk full")
        return orig_open(path, mode, *a, **k)  # type: ignore[misc]

    monkeypatch.setattr(builtins, "open", _open_err)
    st = s.get_emoji(emj)
    assert isinstance(st, BytesIO)


@pytest.mark.parmoji
def test_disk_cache_read_error_falls_back_to_network(monkeypatch, tmp_path):
    s = _SpyCDN(disk_cache=True)
    emj = "😀"
    key = hashlib.blake2b(f"{emj}_{s.STYLE}".encode(), digest_size=16).hexdigest()
    assert s._cache_dir is not None
    png = s._cache_dir / f"{key}.png"
    png.write_bytes(b"not a png")

    # Make reading the cache raise an error to hit the except branch
    import builtins

    orig_open = builtins.open

    def _open_err(path, mode="r", *a, **k):  # noqa: ANN001
        if str(path).endswith(f"{key}.png") and "r" in mode:
            raise OSError("cannot read")
        return orig_open(path, mode, *a, **k)  # type: ignore[misc]

    monkeypatch.setattr(builtins, "open", _open_err)
    st = s.get_emoji(emj)
    assert isinstance(st, BytesIO)


@pytest.mark.parmoji
def test_normal_save_to_cache_error_handled(monkeypatch):
    s = _SpyCDN(disk_cache=True)
    emj = "😀"

    # Force the file write in normal path to raise
    import builtins

    orig_open = builtins.open

    def _open_err(path, mode="r", *a, **k):  # noqa: ANN001
        if str(path).endswith(".png") and "w" in mode:
            raise OSError("no space")
        return orig_open(path, mode, *a, **k)  # type: ignore[misc]

    monkeypatch.setattr(builtins, "open", _open_err)
    st = s.get_emoji(emj)
    assert isinstance(st, BytesIO)
