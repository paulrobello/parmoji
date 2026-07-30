"""Tests for the PIL_VERSION parse guard (helpers._parse_pil_version)."""

from __future__ import annotations

import pytest

from parmoji.helpers import _parse_pil_version


@pytest.mark.parmoji
@pytest.mark.parametrize(
    "version, expected",
    [
        ("9.2.0", (9, 2, 0)),
        ("12.3.0", (12, 3, 0)),
        # Prerelease suffix on a segment stops further parsing.
        ("12.3.0.dev0", (12, 3, 0)),
        # A release-candidate suffix on the patch segment is stripped to its int.
        ("11.0.0rc1", (11, 0, 0)),
        # PEP 440 local build segment.
        ("10.2.0+local", (10, 2, 0)),
        # Two-component version still compares correctly.
        ("11.0", (11, 0)),
    ],
)
def test_parse_pil_version_handles_prereleases(version: str, expected: tuple[int, ...]) -> None:
    assert _parse_pil_version(version) == expected


@pytest.mark.parmoji
def test_parse_pil_version_comparable_for_has_getlength() -> None:
    # The guard exists so HAS_GETLENGTH = PIL_VERSION >= (9, 2, 0) never crashes
    # on a prerelease. Verify the parsed tuple is orderable against (9, 2, 0).
    parsed = _parse_pil_version("12.3.0.dev0")
    assert parsed >= (9, 2, 0)
