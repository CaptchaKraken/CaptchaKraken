"""find_grid turns the element detector's `grid` and `cell` boxes into a lattice the
solver can number: whole rows of one length, in reading order, inside the grid.

The detector is stubbed, so these pin find_grid's own reading of its output; whether
the network finds the boxes is `test_grid_detection_ci` and the real-board tests.
"""
import pytest

import captchakraken.pointer.detector as detector
from captchakraken.tool_calls.find_grid import find_grid


def _det(cls, box, score=0.95):
    return {"class": cls, "box": list(box), "score": score}


def _lattice(rows, cols, x0=10, y0=50, tile=100, gap=6, jitter=0):
    """Cell boxes of a rows x cols board, top-left first, each nudged by `jitter` px."""
    out = []
    for r in range(rows):
        for c in range(cols):
            j = jitter * ((r * cols + c) % 3 - 1)
            x, y = x0 + c * (tile + gap), y0 + r * (tile + gap) + j
            out.append((x, y, x + tile, y + tile))
    return out


def _grid_box(cells):
    return (min(c[0] for c in cells) - 4, min(c[1] for c in cells) - 4,
            max(c[2] for c in cells) + 4, max(c[3] for c in cells) + 4)


@pytest.fixture
def detected(monkeypatch):
    seen = {}

    def use(dets):
        seen["dets"] = dets

    monkeypatch.setattr(detector, "detect_file", lambda _path: seen["dets"])
    return use


def test_cells_come_back_in_reading_order_whatever_order_they_were_found_in(detected):
    cells = _lattice(3, 3, jitter=3)
    detected([_det("grid", _grid_box(cells))] + [_det("cell", c) for c in reversed(cells)])
    assert find_grid("board.png") == [tuple(c) for c in cells]


def test_a_4x4_is_sixteen_cells(detected):
    cells = _lattice(4, 4, tile=80)
    detected([_det("grid", _grid_box(cells))] + [_det("cell", c) for c in cells])
    assert len(find_grid("board.png")) == 16


def test_a_row_missing_a_cell_is_not_a_grid_the_solver_can_number(detected):
    """Numbering 8 boxes as a 3x3 would shift every answer after the gap by one tile."""
    cells = _lattice(3, 3)
    detected([_det("grid", _grid_box(cells))] + [_det("cell", c) for c in cells[:4] + cells[5:]])
    assert find_grid("board.png") is None


def test_cells_outside_the_grid_are_not_part_of_it(detected):
    """An image in the instruction banner is detected as a cell too; it is not a tile."""
    cells = _lattice(3, 3)
    banner = (10, 0, 60, 40)
    detected([_det("grid", _grid_box(cells)), _det("cell", banner)] + [_det("cell", c) for c in cells])
    assert find_grid("board.png") == [tuple(c) for c in cells]


def test_without_a_grid_there_are_no_cells(detected):
    detected([_det("cell", c) for c in _lattice(3, 3)])
    assert find_grid("board.png") is None


def test_an_unsure_grid_is_not_a_grid(detected):
    cells = _lattice(3, 3)
    detected([_det("grid", _grid_box(cells), score=0.2)] + [_det("cell", c) for c in cells])
    assert find_grid("board.png") is None


def test_a_single_row_is_not_a_grid(detected):
    cells = _lattice(1, 4)
    detected([_det("grid", _grid_box(cells))] + [_det("cell", c) for c in cells])
    assert find_grid("board.png") is None


def test_a_tile_read_as_a_jigsaw_piece_still_fills_its_slot(detected):
    """Flat-coloured tiles can read as `draggable`; in the grid's lattice they are cells."""
    cells = _lattice(3, 3)
    dets = [_det("grid", _grid_box(cells))] + [_det("cell", c) for c in cells[:4] + cells[5:]]
    detected(dets + [_det("draggable", cells[4])])
    assert find_grid("board.png") == [tuple(c) for c in cells]


def test_a_tile_the_cells_already_cover_is_not_counted_twice(detected):
    cells = _lattice(3, 3)
    detected([_det("grid", _grid_box(cells))] + [_det("cell", c) for c in cells]
             + [_det("item", (c[0] + 3, c[1] + 3, c[2] - 3, c[3] - 3)) for c in cells])
    assert find_grid("board.png") == [tuple(c) for c in cells]


def test_an_object_inside_a_tile_is_not_a_tile(detected):
    """A small item drawn on one tile is not another cell of the lattice."""
    cells = _lattice(3, 3)
    small = (cells[4][0] + 30, cells[4][1] + 30, cells[4][0] + 60, cells[4][1] + 60)
    detected([_det("grid", _grid_box(cells))] + [_det("cell", c) for c in cells[:4] + cells[5:]]
             + [_det("item", small)])
    assert find_grid("board.png") is None


def test_a_picture_inside_a_tile_read_as_a_cell_does_not_grow_a_column(detected):
    """A Prosopo tile's inset photo was detected as a cell of its own (0.998); its row came back with four."""
    cells = _lattice(3, 3)
    t = cells[5]
    inset = (t[0] + 60, t[1] + 2, t[2] - 2, t[1] + 80)
    detected([_det("grid", _grid_box(cells))] + [_det("cell", c) for c in cells] + [_det("cell", inset, 0.998)])
    assert find_grid("board.png") == [tuple(c) for c in cells]
