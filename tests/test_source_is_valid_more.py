from __future__ import annotations

import pytest

from parmoji.source import MAX_EMOJI_SEQ_LEN, is_valid_emoji


@pytest.mark.parmoji
def test_is_valid_emoji_edge_cases_and_heuristics():
    assert is_valid_emoji("") is False
    assert is_valid_emoji("a" * (MAX_EMOJI_SEQ_LEN + 1)) is False
    # Text-only dingbat without VS-16 rejected
    assert is_valid_emoji("\u2713") is False
    # Variation selector alone or ZWJ should count as emoji-ish for fallback
    assert is_valid_emoji("\ufe0f") is True
    assert is_valid_emoji("\u200d") is True
    # Known emoji sanity
    assert is_valid_emoji("☕\ufe0f") is True
