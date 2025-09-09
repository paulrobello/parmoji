from __future__ import annotations

import pytest

from parmoji import helpers as H
from PIL import ImageFont


@pytest.mark.parmoji
def test_getsize_multiline_mixed_nodes():
    w, h = H.getsize("A😀\nB", font=ImageFont.load_default(), spacing=3, emoji_scale_factor=1.0)
    assert w > 0 and h > 0
