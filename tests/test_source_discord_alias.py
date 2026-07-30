"""Tests for the DiscordEmojiSource non-breaking alias (audit Low item).

DiscordEmojiSourceMixin inherits HTTPBasedSource concretely despite the
"Mixin" name. Renaming would be a public API break, so DiscordEmojiSource
was added as the preferred alias with DiscordEmojiSourceMixin retained as a
deprecated alias. These tests pin the alias contract.
"""

from __future__ import annotations

import parmoji.source as source_mod
from parmoji.source import DiscordEmojiSource, DiscordEmojiSourceMixin


def test_discord_alias_is_same_class():
    # The alias must be the exact same class object (not a subclass).
    assert DiscordEmojiSource is DiscordEmojiSourceMixin


def test_discord_alias_in_module_all():
    # Both names must be exported via __all__ so `from parmoji.source import *`
    # and static analyzers see the preferred name.
    assert "DiscordEmojiSource" in source_mod.__all__
    assert "DiscordEmojiSourceMixin" in source_mod.__all__


def test_discord_alias_subclasses_http_based_source():
    # Sanity: the alias still refers to the class that adds Discord support
    # atop HTTPBasedSource (the real mixin-y behavior lives at this layer).
    from parmoji.source import HTTPBasedSource

    assert issubclass(DiscordEmojiSource, HTTPBasedSource)
    assert hasattr(DiscordEmojiSource, "get_discord_emoji")
