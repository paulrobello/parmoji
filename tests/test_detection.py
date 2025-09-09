import unicodedata

import pytest

from parmoji.helpers import NodeType, is_emoji, to_nodes
from parmoji.source import is_valid_emoji


@pytest.mark.parmoji
def test_detects_zwj_sequence_as_single_emoji():
    # Family: man, woman, girl, boy
    zwj = "👨\u200d👩\u200d👧\u200d👦"
    nodes = to_nodes(zwj)
    assert len(nodes) == 1
    assert len(nodes[0]) == 1
    node = nodes[0][0]
    assert node.type is NodeType.emoji
    assert node.content == zwj


@pytest.mark.parmoji
def test_detects_regional_indicator_flag_as_single_emoji():
    flag = "🇺🇸"  # Regional indicator sequence (two code points)
    nodes = to_nodes(flag)
    assert len(nodes) == 1
    assert len(nodes[0]) == 1
    node = nodes[0][0]
    assert node.type is NodeType.emoji
    assert node.content == flag


@pytest.mark.parmoji
def test_detects_skin_tone_modifier_combination_as_single_emoji():
    thumbs_medium = "👍🏽"
    nodes = to_nodes(thumbs_medium)
    assert len(nodes) == 1
    assert len(nodes[0]) == 1
    assert nodes[0][0].type is NodeType.emoji


@pytest.mark.parmoji
def test_discord_emoji_is_parsed_and_id_extracted():
    snowflake = "123456789012345678"
    s = f"<:blob:{snowflake}>"
    nodes = to_nodes(s)
    assert len(nodes) == 1
    assert len(nodes[0]) == 1
    node = nodes[0][0]
    assert node.type is NodeType.discord_emoji
    assert node.content == snowflake


@pytest.mark.parmoji
def test_variation_selector_16_is_treated_as_emoji():
    # Hot beverage with VS-16
    coffee_emoji = "☕\ufe0f"
    assert is_emoji(coffee_emoji)
    nodes = to_nodes(coffee_emoji)
    assert nodes[0][0].type is NodeType.emoji


@pytest.mark.parmoji
def test_text_presentation_dingbats_not_considered_emoji_for_fetch():
    # Base check mark (text symbol) should not be fetched as emoji without VS-16
    base_check = "\u2713"  # ✓
    assert unicodedata.category(base_check) == "So"
    # helpers.is_emoji may treat some single-codepoint symbols as emoji for layout,
    # but the CDN fetch validator should reject base text symbols.
    assert is_valid_emoji(base_check) is False
    assert is_valid_emoji("☕\ufe0f") is True  # sanity: with VS-16
