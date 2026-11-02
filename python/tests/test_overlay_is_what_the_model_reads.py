"""The model reads what this draws and was never trained to invent a numbering; a wrong overlay does not error,
reCAPTCHA 4x4 simply scores zero and looks like a broken model.
"""

import numpy as np
import pytest
from PIL import Image

from captchakraken.overlay import add_overlays_to_image


def _blank(path, size=(400, 300), color=(255, 255, 255)):
    Image.new("RGB", size, color).save(path)
    return str(path)


def _pixels(path):
    return np.array(Image.open(path).convert("RGB"))


def _changed_mask(before, after):
    return np.any(before != after, axis=2)


def test_a_normalised_box_is_drawn_where_it_was_asked_for(tmp_path):
    src = _blank(tmp_path / "in.png")
    before = _pixels(src)
    out = str(tmp_path / "out.png")

    add_overlays_to_image(src, [{"bbox": [0.5, 0.5, 0.9, 0.9], "number": 7}], output_path=out)

    changed = _changed_mask(before, _pixels(out))
    assert changed.any(), "nothing was drawn at all"

    ys, xs = np.nonzero(changed)
    assert xs.min() >= 150, f"drawing began at x={xs.min()}, far left of the requested box"
    assert ys.min() >= 100, f"drawing began at y={ys.min()}, far above the requested box"
    assert xs.max() <= 399 and ys.max() <= 299


def test_a_pixel_box_is_read_as_x_y_width_height_not_as_corners(tmp_path):
    """Reading [x, y, w, h] as corners draws a box ending at w, silently."""
    src = _blank(tmp_path / "in.png")
    before = _pixels(src)
    out = str(tmp_path / "out.png")

    add_overlays_to_image(src, [{"bbox": [300, 100, 80, 80]}], output_path=out)

    changed = _changed_mask(before, _pixels(out))
    xs = np.nonzero(changed)[1]
    assert xs.max() >= 370, "the right edge of an [x, y, w, h] box was not drawn at x+w"


def test_the_source_is_left_alone_when_an_output_path_is_given(tmp_path):
    src = _blank(tmp_path / "in.png")
    before = _pixels(src)
    out = str(tmp_path / "out.png")

    add_overlays_to_image(src, [{"bbox": [0.1, 0.1, 0.4, 0.4], "number": 1}], output_path=out)

    assert np.array_equal(before, _pixels(src)), "the source image was modified"
    assert not np.array_equal(before, _pixels(out)), "the output image was not drawn on"


def test_no_output_path_overwrites_the_source(tmp_path):
    src = _blank(tmp_path / "in.png")
    before = _pixels(src)

    add_overlays_to_image(src, [{"bbox": [0.1, 0.1, 0.4, 0.4], "number": 1}])

    assert not np.array_equal(before, _pixels(src))


def test_an_empty_box_list_still_produces_a_readable_image(tmp_path):
    src = _blank(tmp_path / "in.png")
    out = str(tmp_path / "out.png")

    add_overlays_to_image(src, [], output_path=out)

    assert np.array_equal(_pixels(src), _pixels(out))


def test_the_result_is_rgb_so_a_later_jpeg_save_cannot_fail(tmp_path):
    """A leftover alpha channel raises 'cannot write mode RGBA as JPEG' a stage away from the overlay that caused it."""
    src = _blank(tmp_path / "in.png")
    out = str(tmp_path / "out.png")

    add_overlays_to_image(src, [{"bbox": [0.2, 0.2, 0.6, 0.6], "text": "cars"}], output_path=out)

    with Image.open(out) as img:
        assert img.mode == "RGB"


def test_a_box_without_a_bbox_raises_instead_of_writing_a_wrong_overlay(tmp_path):
    src = _blank(tmp_path / "in.png")

    with pytest.raises(KeyError):
        add_overlays_to_image(src, [{"number": 3}], output_path=str(tmp_path / "out.png"))


def test_a_missing_source_image_raises(tmp_path):
    with pytest.raises(Exception):
        add_overlays_to_image(
            str(tmp_path / "nope.png"), [{"bbox": [0.1, 0.1, 0.2, 0.2]}],
            output_path=str(tmp_path / "out.png"),
        )
