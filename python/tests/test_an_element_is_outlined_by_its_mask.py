"""Numbering detected elements and drawing them (`pointer/elements.py`, `pointer/marks.py`)."""
import hashlib
import os
import sys

import numpy as np
from PIL import Image

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from captchakraken.pointer import elements as E
from captchakraken.pointer import marks as M


def el(cls, x0, y0, m, score=0.9):
    """An element whose mask `m` (bool array) sits at (x0, y0)."""
    h, w = m.shape
    return {"class": cls, "box": [x0, y0, x0 + w, y0 + h], "score": score, "mask": ((x0, y0), m)}


def square(n):
    return np.ones((n, n), bool)


def ell(n=60, t=10):
    """An L: a long twisty shape's simplest case. Its box's far corner is empty."""
    m = np.zeros((n, n), bool)
    m[:, :t] = True
    m[-t:, :] = True
    return m


def test_cells_number_row_major_and_furniture_is_not_numbered():
    cells = [el("cell", 10 + 70 * c, 10 + 70 * r, square(60)) for r in range(3) for c in range(3)]
    shuffled = [cells[i] for i in (4, 8, 0, 2, 6, 1, 3, 7, 5)]
    dets = shuffled + [el("grid", 5, 5, square(210)), el("click_area", 0, 0, square(220)),
                       el("submit", 150, 230, np.ones((20, 60), bool))]
    els = E.number(dets)
    assert [e["box"][:2] for e in els[:9]] == [c["box"][:2] for c in cells]
    assert [e["class"] for e in els] == ["cell"] * 9 + ["button"]


def test_a_weak_detection_is_not_shown():
    assert E.number([el("item", 0, 0, square(20), score=0.2)]) == []


def test_a_point_in_the_box_but_off_the_mask_names_nothing():
    els = [el("item", 100, 100, ell())]
    size = (400, 400)
    # On the L's stem.
    assert E.element_at([105 / 400 * 1000, 120 / 400 * 1000], size, els) == 0
    # The box's empty far corner.
    assert E.element_at([150 / 400 * 1000, 115 / 400 * 1000], size, els) is None


def test_a_ring_holds_its_own_centre_and_an_edge_holds_a_near_miss():
    ring = square(40)
    ring[10:30, 10:30] = False
    els = [el("item", 100, 100, ring)]
    size = (400, 400)
    assert E.element_at([120 / 400 * 1000, 120 / 400 * 1000], size, els) == 0
    assert E.element_at([141 / 400 * 1000, 120 / 400 * 1000], size, els) == 0
    assert E.element_at([150 / 400 * 1000, 120 / 400 * 1000], size, els) is None


def test_the_smallest_element_under_a_point_wins():
    els = [el("cell", 0, 0, square(100)), el("item", 40, 40, square(20))]
    assert E.element_at([50 / 200 * 1000, 50 / 200 * 1000], (200, 200), els) == 1


def test_the_outline_follows_the_mask_not_its_box():
    img = Image.new("RGB", (200, 200), (255, 255, 255))
    out = np.array(M.draw(img, [el("item", 50, 50, ell())]))
    drawn = (out != 255).any(-1)
    # The L's own outer corner is outlined...
    assert drawn[50, 50]
    # ...but its box's empty corner (above the bar, right of the stem) is not.
    assert not drawn[55:99, 65:109].any()


def test_the_outline_is_one_pixel_wide():
    img = Image.new("RGB", (200, 200), (255, 255, 255))
    out = np.array(M.draw(img, [el("item", 50, 50, square(80))]))
    c = M.colour(1)
    line = (out == c).all(-1)
    # A row through the square's middle crosses its outline exactly twice.
    assert line[90].sum() == 2


def test_every_element_gets_a_numbered_tag_in_its_colour_big_enough_to_read():
    img = Image.new("RGB", (300, 300), (255, 255, 255))
    els = [el("cell", 20 + 90 * c, 40, square(80)) for c in range(3)]
    out = np.array(M.draw(img, els))
    for n in (1, 2, 3):
        tw, th = M.tag_size(n)
        # A digit's 7 font rows at SCALE span more than one 16 px ViT patch.
        assert th >= 16 + 2 * M.PAD and tw <= 5 * M.SCALE + 2 * M.PAD
        assert (out == M.colour(n)).all(-1).sum() > 4 * 80


def test_tags_of_neighbours_do_not_cover_each_other():
    img = Image.new("RGB", (300, 300), (255, 255, 255))
    els = E.number([el("item", 100 + 6 * k, 100, square(12)) for k in range(4)])
    out = np.array(M.draw(img, els))
    white_digits = (out == 255).all(-1)
    # Every tag's digit pixels survived: no later tag was painted over an earlier one.
    for n in range(1, 5):
        assert (out == M.colour(n)).all(-1).any()
    assert white_digits.any()


def test_the_look_is_frozen():
    """The model is trained on these exact pixels. A change here is a retrain."""
    img = Image.new("RGB", (128, 128), (200, 210, 220))
    els = [el("cell", 8, 8, square(50)), el("item", 70, 70, ell(40, 8)), el("button", 10, 100, np.ones((12, 40), bool))]
    digest = hashlib.sha256(np.array(M.draw(img, els)).tobytes()).hexdigest()
    assert digest == FROZEN


FROZEN = "f597cbc52c7442b96bdd314a4efbf65760c7670e10b42775afb472ebdaf87992"
