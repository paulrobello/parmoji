from __future__ import annotations

import types

import pytest

from parmoji import helpers as H


@pytest.mark.parmoji
def test_is_emoji_uses_library_fastpath():
    # With real emoji library, common emoji should return True via emoji_count
    assert H.is_emoji("😀") is True


@pytest.mark.parmoji
def test_is_emoji_set_lookup_when_library_silent(monkeypatch):
    # Force emoji_count to return 0 so we hit EMOJI_SET path
    monkeypatch.setattr(H.emoji, "emoji_count", lambda s: 0)
    assert "😀" in H.EMOJI_SET  # sanity: dataset contains grinning face
    assert H.is_emoji("😀") is True


@pytest.mark.parmoji
def test_is_emoji_zwj_vs16_sequence_without_library(monkeypatch):
    # Simulate no detection by library and not in EMOJI_SET; rely on ZWJ/VS-16 rule
    monkeypatch.setattr(H.emoji, "emoji_count", lambda s: 0)
    # Use a plain letter with VS-16; not in the data set but contains \ufe0f
    seq = "A\ufe0f"
    assert seq not in H.EMOJI_SET
    assert H.is_emoji(seq) is True


@pytest.mark.parmoji
def test_is_emoji_category_fallback_for_single_char(monkeypatch):
    # © (So category) should be considered emoji-like via fallback
    monkeypatch.setattr(H.emoji, "emoji_count", lambda s: 0)
    assert H.is_emoji("©") is True


@pytest.mark.parmoji
def test_is_emoji_library_exception_fallback(monkeypatch):
    # If emoji_count raises, function should fall back and still work
    def _boom(_s):  # noqa: ARG001
        raise RuntimeError("boom")

    monkeypatch.setattr(H.emoji, "emoji_count", _boom)
    assert H.is_emoji("©") is True


@pytest.mark.parmoji
def test_find_emojis_and_to_nodes_multiline_and_repr():
    s = "Hello 😀\n<:xname:123456789012345678>"
    spans = H.find_emojis_in_text(s)
    # Expect at least one span
    assert len(spans) >= 1

    nodes = H.to_nodes(s)
    # Two lines
    assert len(nodes) == 2
    # First line ends with emoji node
    assert nodes[0][-1].type is H.NodeType.emoji
    # Second line is discord emoji node with numeric content
    assert nodes[1][0].type is H.NodeType.discord_emoji
    assert nodes[1][0].content.isdigit()

    # __repr__ coverage
    _ = repr(nodes[0][-1])


@pytest.mark.parmoji
def test_parse_line_no_emoji_and_text_segments(monkeypatch):
    # Empty line yields empty nodes
    assert H.to_nodes("") == []

    # Text-emoji-text segments captured appropriately
    # Make emoji_count return 1 only for the single emoji to avoid greedy matches
    monkeypatch.setattr(H.emoji, "emoji_count", lambda s: 1 if s == "😀" else 0)
    nodes = H.to_nodes("a😀b")
    assert [n.type for n in nodes[0]] == [H.NodeType.text, H.NodeType.emoji, H.NodeType.text]
    assert nodes[0][0].content == "a" and nodes[0][2].content == "b"


@pytest.mark.parmoji
def test_parse_line_plain_text_only():
    import parmoji.helpers as H

    nodes = H.to_nodes("justtext")
    assert len(nodes) == 1 and len(nodes[0]) == 1
    assert nodes[0][0].type is H.NodeType.text and nodes[0][0].content == "justtext"
