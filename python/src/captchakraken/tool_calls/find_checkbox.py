"""Where the driver clicks first, before any model runs: the tick box of a vendor's
checkbox widget, as the element detector's `checkbox` class finds it. Neither a
false positive nor a false negative raises."""

from typing import Optional, Tuple

#: Measured on widgets in a language the detector never trained on: every one of
#: 96 tick boxes scored >= 0.997, a ticked or passed widget 0, and the highest
#: `checkbox` score on 600 real puzzle boards was 0.145. 0.6 sits far from both.
MIN_SCORE = 0.6


def find_checkbox(image_path: str) -> Optional[Tuple[int, int, int, int]]:
    """(x, y, w, h) of the most confident tick box in pixels, or None."""
    from ..pointer.detector import detect_file

    boxes = [d for d in detect_file(image_path) if d["class"] == "checkbox" and d["score"] >= MIN_SCORE]
    if not boxes:
        return None
    x0, y0, x1, y1 = max(boxes, key=lambda d: d["score"])["box"]
    return int(round(x0)), int(round(y0)), int(round(x1 - x0)), int(round(y1 - y0))
