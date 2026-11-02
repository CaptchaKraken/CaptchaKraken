"""Board drawing for tests, in numpy and Pillow: the client no longer depends on OpenCV.

Arrays are BGR (the order the tests were written in), and `imwrite` saves them as an
image file shows them, so a board drawn here is the board the old drawing produced.
"""
import colorsys

import numpy as np
from PIL import Image


def hsv_bgr(h: int, s: int, v: int) -> np.ndarray:
    """One colour on OpenCV's 8-bit HSV scale (hue 0-179) as a BGR uint8 triple."""
    r, g, b = colorsys.hsv_to_rgb(h / 180.0, s / 255.0, v / 255.0)
    return np.array([round(b * 255), round(g * 255), round(r * 255)], np.uint8)


def imwrite(path: str, bgr: np.ndarray) -> None:
    Image.fromarray(np.ascontiguousarray(bgr[..., ::-1])).save(path)


def fill_rect(img: np.ndarray, p0, p1, bgr) -> None:
    """Fill the rectangle with corners p0 and p1, both inclusive."""
    (x0, y0), (x1, y1) = p0, p1
    img[y0:y1 + 1, x0:x1 + 1] = bgr


def fill_circle(img: np.ndarray, centre, radius: int, bgr) -> None:
    yy, xx = np.ogrid[:img.shape[0], :img.shape[1]]
    img[(xx - centre[0]) ** 2 + (yy - centre[1]) ** 2 <= radius ** 2] = bgr
