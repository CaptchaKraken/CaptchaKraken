"""Two Tier 3 boards that reached the wrong expert, captured exactly as the engine received them (2026-10-27).

The grocery board is a 6x3 of cards. On macOS its frame scrollbars shift the layout so one tile pair's split
falls just outside tolerance, and it was read as a 3x3 of tile pairs; the grid expert then clicked all nine.
The photo board is a real 3x3 that sits off-centre in its panel; its true gutters came up 0.3px short of
corroboration, find_grid returned nothing, and the pixel expert answered a grid.
"""

import os
import sys

import pytest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from captchakraken.tool_calls.find_grid import find_grid

pytest.importorskip("cv2")
FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "grid")


def test_a_6x3_card_board_is_not_a_3x3_of_tile_pairs():
    boxes = find_grid(os.path.join(FIXTURES, "groceries_6x3_mac.png")) or []
    assert len(boxes) != 9, "a 6x3 grocery board was read as a 3x3 of tile pairs"


def test_an_off_centre_3x3_photo_grid_is_found():
    boxes = find_grid(os.path.join(FIXTURES, "photos_3x3_offcentre.png")) or []
    assert len(boxes) == 9, f"expected the 3x3 photo grid, got {len(boxes)} cells"
