"""Slide boards drawn in numpy for the tracker and the drivers: a jigsaw piece on a track, a disc that turns in place,
and a piece the pointer carries. Each renders the shot the page would show after the handle travelled `s`, and has
a handle and filled track that move too and, by default, a badge animating elsewhere."""

import math

import numpy as np
from scipy import ndimage


from captchakraken.tool_calls import slide_tracker as st


_CROSS = ndimage.generate_binary_structure(2, 1)


def _blur(img, sigma):
    """Gaussian smoothing of the two spatial axes, mirrored at the border."""
    return ndimage.gaussian_filter(img, (sigma, sigma) + (0,) * (img.ndim - 2), mode="mirror")


def _blur3(img, sigma):
    """A 3x3 Gaussian of `sigma`, the soft edge a page rasterizer leaves."""
    k = np.exp(-np.array([1.0, 0.0, 1.0]) / (2 * sigma * sigma))
    k /= k.sum()
    return ndimage.correlate1d(ndimage.correlate1d(img, k, axis=0, mode="mirror"), k, axis=1, mode="mirror")


def _warp(img, m, mode="grid-constant"):
    """`img` moved by the forward 2x3 matrix `m` (x, y order), bilinear, into a canvas of its own size."""
    inv = np.linalg.inv(np.vstack([m, [0, 0, 1]]))
    rows = np.array([[inv[1, 1], inv[1, 0]], [inv[0, 1], inv[0, 0]]])
    matrix, offset = np.eye(img.ndim), np.zeros(img.ndim)
    matrix[:2, :2], offset[:2] = rows, (inv[1, 2], inv[0, 2])
    return ndimage.affine_transform(img.astype(np.float32), matrix, offset, order=1, mode=mode)


def _disc(shape, c, r):
    yy, xx = np.mgrid[0:shape[0], 0:shape[1]]
    return (xx - c[0]) ** 2 + (yy - c[1]) ** 2 <= r * r


def _stroke(img, path, color):
    """A one-pixel `path` (boolean) drawn three pixels wide with round ends, as a 2 px browser stroke rasterizes."""
    img[ndimage.binary_dilation(path, _CROSS)] = color


def _box(shape, x1, y1, x2, y2):
    """The pixels of the rectangle with corners (x1, y1) and (x2, y2), both inclusive."""
    out = np.zeros(shape[:2], bool)
    out[max(y1, 0):y2 + 1, max(x1, 0):x2 + 1] = True
    return out


def _texture(h, w, seed, blur=2.0):
    rng = np.random.RandomState(seed)
    base = _blur(rng.rand(h, w, 3).astype(np.float32), blur)
    base = (base - base.min()) / (np.ptp(base) + 1e-6)
    yy, xx = np.mgrid[0:h, 0:w]
    stripes = 0.5 + 0.5 * np.sin(xx / 7.0 + yy / 11.0)[..., None]
    return np.clip(40 + 170 * (0.7 * base + 0.3 * stripes), 0, 255).astype(np.float32)


def _jigsaw_mask(size, scale):
    """A square with a knob on top and on the right, the usual piece outline."""
    k = int(round(8 * scale))
    shape = (size + 2 * k, size + 2 * k)
    m = _box(shape, k, k, k + size - 1, k + size - 1) | _disc(shape, (k + size // 2, k), k)
    return (m | _disc(shape, (k + size - 1, k + size // 2), k)).astype(np.uint8), k


def _paste(canvas, layer, alpha, x, y):
    """Composite `layer` (with `alpha` 0..1) so its top-left lands at the float point (x, y)."""
    h, w = canvas.shape[:2]
    m = np.float32([[1, 0, x], [0, 1, y]])
    lay = _warp(_onto(layer, h, w), m)
    al = _warp(_onto(alpha, h, w), m)[..., None]
    return canvas * (1 - al) + lay * al


def _onto(layer, h, w):
    """`layer` at the top-left of an h x w canvas, cropped to it."""
    out = np.zeros((h, w) + layer.shape[2:], np.float32)
    lh, lw = min(h, layer.shape[0]), min(w, layer.shape[1])
    out[:lh, :lw] = layer[:lh, :lw]
    return out


class _Board:
    """Shared furniture: a track with a handle that follows s 1:1 and a fill behind it, and an animated badge."""

    def __init__(self, scale, badge):
        self.k = scale
        self.w, self.h = int(340 * scale), int(220 * scale)
        self.badge = badge
        self.frames = 0
        self.handle0 = (30 * scale, 197 * scale)

    def furniture(self, img, s):
        k = self.k
        img[_box(img.shape, int(10 * k), int(185 * k), int(330 * k), int(209 * k))] = (225, 225, 225)
        hx = self.handle0[0] + s
        img[_box(img.shape, int(10 * k), int(185 * k), int(hx), int(209 * k))] = (230, 190, 120)
        knob = _box(img.shape, int(hx - 18 * k), int(183 * k), int(hx + 18 * k), int(211 * k))
        img[knob] = (255, 255, 255)
        _stroke(img, knob & ~ndimage.binary_erosion(knob, np.ones((3, 3))), (90, 90, 90))
        for i in (-6, 0, 6):
            x = int(hx + i * k)
            _stroke(img, _box(img.shape, x, int(190 * k), x, int(204 * k)), (120, 120, 120))
        if self.badge:
            # A badge spinning in the top-right corner, a step every frame whatever the handle does.
            self.frames += 1
            a = self.frames * 0.9
            c = (int(310 * k + 10 * k * math.cos(a)), int(25 * k + 10 * k * math.sin(a)))
            img[_disc(img.shape, c, int(7 * k))] = (40, 200, 40)
            img[_disc(img.shape, c, int(3 * k))] = (250, 250, 60)
        return img


class JigsawBoard(_Board):
    """`picture_ends` (shot px): below it the ground is flat white down to the track, the way a widget frames its
    picture, and the piece rests `y0` from the top, so it can sit just above that flat strip. `flat_rest`: the
    piece rests on flat sky with a flat dark block just ahead of it, as on a Yidun photo, while the slot keeps its
    texture. `flat_face`: the piece is one flat tone inside its rim, as GeeTest draws a piece cut from a banner; a
    colour sets that tone, and `blank_rim` draws its rim in it too. `shadow=False` draws none.
    `decoy`: a still copy of the piece drawn `decoy` px above the slot. `pale_band`: the ground along the rail from
    `pale_band[0]` to `pale_band[1]` (shot px) is the piece's own face tone, as a white phone screen is to a white
    piece."""

    def __init__(self, ratio=1.0, scale=1.0, badge=True, seed=3, y0=70, picture_ends=None, flat_rest=False,
                 flat_face=False, decoy=None, pale_band=None, blank_rim=False, shadow=True):
        super().__init__(scale, badge)
        k = scale
        self.ratio = ratio
        self.bg = _texture(self.h, self.w, seed)
        if picture_ends is not None:
            self.bg[int(picture_ends):] = 250
        self.size = int(44 * k)
        self.mask, self.knob = _jigsaw_mask(self.size, k)
        self.x0, self.y0 = 12 * k, y0 * k                   # the piece's top-left (mask box) at rest
        if flat_rest:
            mh, mw = self.mask.shape
            top, right = int(self.y0 - 12 * k), int(self.x0 + mw)
            self.bg[top:int(self.y0 + mh + 12 * k), :right + int(30 * k)] = 205
            self.bg[top:int(self.y0 + mh + 12 * k), right - int(4 * k):right + int(30 * k)] = 35
        self.slot = (200 * k, 70 * k)
        sx, sy = int(self.slot[0]), int(self.slot[1])
        mh, mw = self.mask.shape
        self.piece = self.bg[sy:sy + mh, sx:sx + mw].copy()
        face = flat_face if isinstance(flat_face, tuple) else (232, 230, 226)
        if flat_face:
            self.piece[:] = face
        if pale_band is not None:
            rows = slice(int(self.y0 - 10 * k), int(self.y0 + mh + 10 * k))
            self.bg[rows, int(pale_band[0]):int(pale_band[1])] = face
        square = np.ones((3, 3), bool)
        edge = ndimage.binary_dilation(self.mask, square) & ~ndimage.binary_erosion(self.mask, square, border_value=1)
        self.piece[edge] = face if blank_rim else (250, 250, 250)
        hole = self.bg.copy()
        region = hole[sy:sy + mh, sx:sx + mw]
        region[self.mask > 0] *= 0.45
        self.ground = hole
        self.alpha = _blur3(self.mask.astype(np.float32), 0.6)
        self.shadow = _blur(self.mask.astype(np.float32), 2.5 * k) * (0.5 if shadow else 0.0)
        if decoy is not None:
            self.ground = _paste(self.ground, self.piece, self.alpha, sx, sy - decoy * k)

    def footprint(self):
        """Where the piece, and separately its shadow, sit at rest: boolean masks in shot pixels."""
        def at(layer, dx):
            m = np.float32([[1, 0, self.x0 + dx], [0, 1, self.y0 + dx]])
            return _warp(_onto(layer, self.h, self.w), m) > 0.05
        return at(self.alpha, 0.0), at(self.shadow, 3 * self.k)

    def centre(self, s=0.0):
        """The piece's centre (of its square, not its knobs) after the handle travelled s."""
        return (self.x0 + self.knob + self.size / 2 + self.ratio * s, self.y0 + self.knob + self.size / 2)

    @property
    def goal(self):
        return (self.slot[0] + self.knob + self.size / 2, self.slot[1] + self.knob + self.size / 2)

    def handle(self):
        return self.handle0

    def render(self, s):
        x = self.x0 + self.ratio * s
        img = self.ground.copy()
        img = _paste(img, np.zeros_like(self.piece), self.shadow, x + 3 * self.k, self.y0 + 3 * self.k)
        img = _paste(img, self.piece, self.alpha, x, self.y0)
        return self.furniture(np.clip(img, 0, 255).astype(np.uint8), s)


class DiscBoard(_Board):
    """A picture disc turned off upright inside a static ring; the handle turns it `deg_per_px` per pixel."""

    def __init__(self, deg_per_px=360 / 260, start_deg=-70.0, scale=1.0, badge=True, seed=5):
        super().__init__(scale, badge)
        k = scale
        self.rate, self.start = deg_per_px, start_deg
        self.c = (170 * k, 92 * k)
        self.r = 60 * k
        self.ring = _texture(self.h, self.w, seed + 1, blur=1.5)
        self.pic = _texture(self.h, self.w, seed, blur=2.5)
        yy, xx = np.mgrid[0:self.h, 0:self.w]
        self.disc = (np.hypot(xx - self.c[0], yy - self.c[1]) <= self.r).astype(np.float32)
        self.disc = _blur3(self.disc, 0.7)

    def angle(self, s=0.0):
        return self.start + self.rate * s

    def seed_point(self):
        return (self.c[0], self.c[1] - 0.8 * self.r)

    def point(self, s=0.0):
        return st.transform_point((self.rate * s, 0.0, 0.0), self.c, self.seed_point())

    @property
    def goal(self):
        # Upright is where the start angle is undone; the 12-o'clock point is wherever that turn carries it.
        return st.transform_point((-self.start, 0.0, 0.0), self.c, self.seed_point())

    def handle(self):
        return self.handle0

    def render(self, s):
        r = math.radians(self.angle(s))
        rot = np.array([[math.cos(r), -math.sin(r)], [math.sin(r), math.cos(r)]])
        c = np.array(self.c)
        turned = _warp(self.pic, np.hstack([rot, (c - rot @ c)[:, None]]), mode="reflect")
        img = self.ring * (1 - self.disc[..., None]) + turned * self.disc[..., None]
        img = np.clip(img, 0, 255).astype(np.uint8)
        yy, xx = np.mgrid[0:self.h, 0:self.w]
        rim = np.abs(np.hypot(xx - int(self.c[0]), yy - int(self.c[1])) - int(self.r + 2 * self.k)) < 0.5
        _stroke(img, rim, (245, 245, 245))
        return self.furniture(img, s)


class CarriedBoard(JigsawBoard):
    """No track: the pointer presses the piece itself and it follows the pointer in two dimensions."""

    def __init__(self, scale=1.0, badge=True):
        super().__init__(1.0, scale, badge)
        self.x0, self.y0 = 30 * scale, 110 * scale

    def handle(self):
        return self.centre()

    def render(self, s):
        dx, dy = s if isinstance(s, (list, tuple)) else (s, 0.0)
        img = self.ground.copy()
        x, y = self.x0 + dx, self.y0 + dy
        img = _paste(img, np.zeros_like(self.piece), self.shadow, x + 3 * self.k, y + 3 * self.k)
        img = _paste(img, self.piece, self.alpha, x, y)
        if self.badge:
            self.frames += 1
            img[_disc(img.shape, (int(310 * self.k), int(25 * self.k + 3 * (self.frames % 4))), int(7 * self.k))] = \
                (40, 200, 40)
        return np.clip(img, 0, 255).astype(np.uint8)
