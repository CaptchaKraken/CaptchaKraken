"""The slide tracker against boards drawn here: a jigsaw piece on a track, a disc that turns in place, and a piece
carried by the pointer itself. Every board has a handle and a filled track that move too, and most have a badge
animating elsewhere, because those are what a diff-based tracker used to mistake for the piece."""

import math

import cv2
import numpy as np
import pytest

from captchakraken.tool_calls import slide_tracker as st


def _texture(h, w, seed, blur=2.0):
    rng = np.random.RandomState(seed)
    base = cv2.GaussianBlur(rng.rand(h, w, 3).astype(np.float32), (0, 0), blur)
    base = (base - base.min()) / (np.ptp(base) + 1e-6)
    yy, xx = np.mgrid[0:h, 0:w]
    stripes = 0.5 + 0.5 * np.sin(xx / 7.0 + yy / 11.0)[..., None]
    return np.clip(40 + 170 * (0.7 * base + 0.3 * stripes), 0, 255).astype(np.float32)


def _jigsaw_mask(size, scale):
    """A square with a knob on top and on the right, the usual piece outline."""
    k = int(round(8 * scale))
    m = np.zeros((size + 2 * k, size + 2 * k), np.uint8)
    cv2.rectangle(m, (k, k), (k + size - 1, k + size - 1), 1, -1)
    cv2.circle(m, (k + size // 2, k), k, 1, -1)
    cv2.circle(m, (k + size - 1, k + size // 2), k, 1, -1)
    return m, k


def _paste(canvas, layer, alpha, x, y):
    """Composite `layer` (with `alpha` 0..1) so its top-left lands at the float point (x, y)."""
    h, w = canvas.shape[:2]
    m = np.float32([[1, 0, x], [0, 1, y]])
    lay = cv2.warpAffine(layer, m, (w, h), flags=cv2.INTER_LINEAR)
    al = cv2.warpAffine(alpha, m, (w, h), flags=cv2.INTER_LINEAR)[..., None]
    return canvas * (1 - al) + lay * al


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
        cv2.rectangle(img, (int(10 * k), int(185 * k)), (int(330 * k), int(209 * k)), (225, 225, 225), -1)
        hx = self.handle0[0] + s
        cv2.rectangle(img, (int(10 * k), int(185 * k)), (int(hx), int(209 * k)), (230, 190, 120), -1)
        cv2.rectangle(img, (int(hx - 18 * k), int(183 * k)), (int(hx + 18 * k), int(211 * k)), (255, 255, 255), -1)
        cv2.rectangle(img, (int(hx - 18 * k), int(183 * k)), (int(hx + 18 * k), int(211 * k)), (90, 90, 90), 2)
        for i in (-6, 0, 6):
            cv2.line(img, (int(hx + i * k), int(190 * k)), (int(hx + i * k), int(204 * k)), (120, 120, 120), 2)
        if self.badge:
            # A badge spinning in the top-right corner, a step every frame whatever the handle does.
            self.frames += 1
            a = self.frames * 0.9
            c = (int(310 * k + 10 * k * math.cos(a)), int(25 * k + 10 * k * math.sin(a)))
            cv2.circle(img, c, int(7 * k), (40, 200, 40), -1)
            cv2.circle(img, c, int(3 * k), (250, 250, 60), -1)
        return img


class JigsawBoard(_Board):
    def __init__(self, ratio=1.0, scale=1.0, badge=True, seed=3):
        super().__init__(scale, badge)
        k = scale
        self.ratio = ratio
        self.bg = _texture(self.h, self.w, seed)
        self.size = int(44 * k)
        self.mask, self.knob = _jigsaw_mask(self.size, k)
        self.x0, self.y0 = 12 * k, 70 * k                   # the piece's top-left (mask box) at rest
        self.slot = (200 * k, 70 * k)
        sx, sy = int(self.slot[0]), int(self.slot[1])
        mh, mw = self.mask.shape
        self.piece = self.bg[sy:sy + mh, sx:sx + mw].copy()
        edge = cv2.dilate(self.mask, np.ones((3, 3), np.uint8)) - cv2.erode(self.mask, np.ones((3, 3), np.uint8))
        self.piece[edge > 0] = (250, 250, 250)
        hole = self.bg.copy()
        region = hole[sy:sy + mh, sx:sx + mw]
        region[self.mask > 0] *= 0.45
        self.ground = hole
        self.alpha = cv2.GaussianBlur(self.mask.astype(np.float32), (3, 3), 0.6)
        self.shadow = cv2.GaussianBlur(self.mask.astype(np.float32), (0, 0), 2.5 * k) * 0.5

    def footprint(self):
        """Where the piece, and separately its shadow, sit at rest: boolean masks in shot pixels."""
        def at(layer, dx):
            m = np.float32([[1, 0, self.x0 + dx], [0, 1, self.y0 + dx]])
            return cv2.warpAffine(layer.astype(np.float32), m, (self.w, self.h)) > 0.05
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
        self.disc = cv2.GaussianBlur(self.disc, (3, 3), 0.7)

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
        m = cv2.getRotationMatrix2D(self.c, -self.angle(s), 1.0)    # OpenCV turns counter-clockwise for +angle
        turned = cv2.warpAffine(self.pic, m, (self.w, self.h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
        img = self.ring * (1 - self.disc[..., None]) + turned * self.disc[..., None]
        img = np.clip(img, 0, 255).astype(np.uint8)
        cv2.circle(img, (int(self.c[0]), int(self.c[1])), int(self.r + 2 * self.k), (245, 245, 245), 2)
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
            cv2.circle(img, (int(310 * self.k), int(25 * self.k + 3 * (self.frames % 4))), int(7 * self.k),
                       (40, 200, 40), -1)
        return np.clip(img, 0, 255).astype(np.uint8)


def _drive(board, seed, goal, probe_s=8.0, max_moves=3, tol=2.0):
    """The driver's loop: press, probe, then follow `next` until done. Returns (final s, moves, last reply)."""
    first, probe = board.render(0.0), board.render(probe_s)
    bounds = (-board.handle0[0] + 10 * board.k, board.w - board.handle0[0] - 10 * board.k)
    kw = dict(probe_s=probe_s, goal=goal, seed=seed, handle=board.handle(), bounds=bounds, tol=tol * board.k)
    reply = st.slide_step(first, probe, probe, s=probe_s, **kw)
    s, hist, moves = probe_s, [], 0
    while not reply["done"] and moves < max_moves:
        s = reply["next"]
        moves += 1
        reply = st.slide_step(first, probe, board.render(s), s=s, history=hist, **kw)
        hist.append(reply["observation"])
    return s, moves, reply


# ── what moved ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize("ratio", [0.8, 1.0, 1.27])
def test_the_seeded_mask_is_the_piece_not_the_handle_or_the_badge(ratio):
    b = JigsawBoard(ratio=ratio)
    seg = st.segment(b.render(0), b.render(8), seed=b.centre(), handle=b.handle())
    piece, shadow = b.footprint()
    # It covers the piece, and everything it holds is the piece or the shadow that travels with it.
    mask = seg.mask.astype(bool)
    # All of the piece but its antialiased rim. Featureless ground hugging the edge looks the same carried or still,
    # so a few pixels of it may come along; nothing further out, where the handle, track and badge are.
    core = cv2.erode(piece.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)
    body = piece | shadow
    near = cv2.dilate(body.astype(np.uint8), np.ones((11, 11), np.uint8)).astype(bool)
    assert (mask & core).sum() >= 0.95 * core.sum()
    assert (mask & ~near).sum() == 0
    assert (mask & ~body).sum() <= 0.05 * piece.sum()
    assert not seg.grabbed


def test_without_a_seed_the_largest_moving_part_that_is_not_the_handle_is_taken():
    b = JigsawBoard(badge=True)
    seg = st.segment(b.render(0), b.render(8), seed=None, handle=b.handle())
    cx, cy = seg.centroid
    px, py = b.centre()
    assert abs(cx - px) < 6 and abs(cy - py) < 6


# ── how it moved ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize("ratio", [0.8, 1.0, 1.27])
def test_translation_is_measured_to_half_a_pixel_across_the_track(ratio):
    b = JigsawBoard(ratio=ratio)
    first, probe = b.render(0), b.render(8)
    seg = st.segment(first, probe, seed=b.centre(), handle=b.handle())
    samples = [st.Sample(8.0, st.measure(first, probe, seg, guess=seg.probe, reach_px=6, reach_deg=3)[0])]
    worst = 0.0
    for s in (0.0, 13.0, 37.5, 61.0, 90.0, 118.3, 150.0):
        params, _ = st.measure(first, b.render(s), seg, guess=st.predict(samples, seg, s))
        got = st.transform_point(params, seg.centroid, b.centre())
        want = b.centre(s)
        worst = max(worst, math.hypot(got[0] - want[0], got[1] - want[1]))
        samples.append(st.Sample(s, params))
    assert worst <= 0.5, f"worst error {worst:.2f}px at ratio {ratio}"


def test_a_disc_turning_in_place_is_measured_to_a_degree_and_its_point_to_a_pixel_and_a_half():
    b = DiscBoard()
    first, probe = b.render(0), b.render(8)
    seg = st.segment(first, probe, seed=b.seed_point(), handle=b.handle())
    assert math.hypot(seg.centroid[0] - b.c[0], seg.centroid[1] - b.c[1]) < 3
    samples = [st.Sample(8.0, st.measure(first, probe, seg, guess=seg.probe, reach_px=6, reach_deg=3)[0])]
    for s in (20.0, 45.0, 80.0, 120.0):
        params, _ = st.measure(first, b.render(s), seg, guess=st.predict(samples, seg, s))
        assert abs(params[0] - b.rate * s) <= 1.0, (s, params)
        got = st.transform_point(params, seg.centroid, b.seed_point())
        want = b.point(s)
        assert math.hypot(got[0] - want[0], got[1] - want[1]) <= 1.5, (s, got, want)
        samples.append(st.Sample(s, params))


# ── the loop ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("ratio", [0.8, 1.0, 1.27])
def test_the_loop_seats_the_piece_within_tolerance_in_three_corrections(ratio):
    b = JigsawBoard(ratio=ratio)
    s, moves, reply = _drive(b, b.centre(), b.goal)
    got = b.centre(s)
    assert reply["done"] and moves <= 3
    assert math.hypot(got[0] - b.goal[0], got[1] - b.goal[1]) <= 2.0, (ratio, s, got, b.goal)


def test_the_loop_turns_a_disc_upright_within_tolerance_in_three_corrections():
    b = DiscBoard()
    s, moves, reply = _drive(b, b.seed_point(), b.goal)
    got = b.point(s)
    assert reply["done"] and moves <= 3
    assert math.hypot(got[0] - b.goal[0], got[1] - b.goal[1]) <= 2.0
    # Two pixels at the point's radius is the angle the loop is entitled to stop at.
    assert abs(b.angle(s)) <= math.degrees(2.0 / (0.8 * b.r)) + 0.1


def test_a_piece_the_pointer_carries_is_steered_in_two_dimensions():
    b = CarriedBoard()
    goal = (b.goal[0], b.goal[1])
    first, probe = b.render(0.0), b.render((8.0, 0.0))
    kw = dict(probe_s=[8.0, 0.0], goal=goal, seed=b.centre(), handle=b.handle(), tol=2.0)
    reply = st.slide_step(first, probe, probe, s=[8.0, 0.0], **kw)
    assert reply["grabbed"]
    moves = 0
    while not reply["done"] and moves < 3:
        s = reply["next"]
        moves += 1
        reply = st.slide_step(first, probe, b.render(tuple(s)), s=s, **kw)
    got = (b.centre()[0] + s[0], b.centre()[1] + s[1])
    assert reply["done"] and moves <= 3
    assert math.hypot(got[0] - goal[0], got[1] - goal[1]) <= 2.0


# ── failing loudly ───────────────────────────────────────────────────────────


def test_an_object_that_never_moves_is_an_error_not_a_position():
    b = JigsawBoard(ratio=0.0, badge=False)

    class Frozen(JigsawBoard):
        def furniture(self, img, s):
            return img                                      # not even the handle moves

    f = Frozen(ratio=0.0, badge=False)
    with pytest.raises(st.TrackingError, match="nothing moved"):
        st.slide_step(f.render(0), f.render(8), f.render(8), probe_s=8, s=8, goal=b.goal, seed=b.centre(),
                      handle=b.handle())


def test_a_point_far_from_anything_that_moved_is_reported_not_guessed():
    b = JigsawBoard(badge=False)
    with pytest.raises(st.TrackingError, match="nothing moved within"):
        st.segment(b.render(0), b.render(8), seed=(280.0, 40.0), handle=b.handle())


def test_a_piece_that_vanishes_is_lost_not_placed():
    b = JigsawBoard(badge=False)
    first, probe = b.render(0), b.render(8)
    blank = first.copy()
    blank[: int(160 * b.k)] = 128                           # the picture area repainted flat: the piece is gone
    with pytest.raises(st.TrackingError, match="lost the object"):
        st.slide_step(first, probe, blank, probe_s=8, s=60, goal=b.goal, seed=b.centre(), handle=b.handle())


# ── device scale ─────────────────────────────────────────────────────────────


def test_a_hidpi_shot_is_tracked_the_same_in_its_own_pixels():
    b = JigsawBoard(ratio=1.27, scale=2.0)
    s, moves, reply = _drive(b, b.centre(), b.goal, probe_s=16.0)
    got = b.centre(s)
    assert reply["done"] and moves <= 3
    assert math.hypot(got[0] - b.goal[0], got[1] - b.goal[1]) <= 2.0 * 2


def test_the_cli_answers_a_slide_step_from_files(tmp_path):
    from captchakraken.cli import slide_step

    b = JigsawBoard()
    paths = []
    for name, s in (("first", 0.0), ("probe", 8.0)):
        p = tmp_path / f"{name}.png"
        cv2.imwrite(str(p), b.render(s))
        paths.append(str(p))
    out = slide_step({"first": paths[0], "probe": paths[1], "current": paths[1], "probe_s": 8, "s": 8,
                      "goal": list(b.goal), "seed": list(b.centre()), "handle": list(b.handle()),
                      "bounds": [-20, 300]})
    assert not out["grabbed"] and not out["done"]
    assert abs(out["pos"][0] - b.centre(8)[0]) < 0.6
    # One 8px probe fixes the ratio to about a percent; the loop's later looks take out the rest.
    want = b.goal[0] - b.centre()[0]
    assert abs(out["next"] - want) <= 0.02 * want
    bad = slide_step({"first": paths[0], "probe": paths[0], "current": paths[0], "probe_s": 8, "s": 8,
                      "goal": list(b.goal), "seed": list(b.centre()), "handle": list(b.handle())})
    assert "error" in bad and "pos" not in bad


def test_the_cv_worker_answers_a_slide_step_request_line(tmp_path):
    """The JSON-line form the TypeScript driver sends through the persistent worker."""
    import json
    import os
    import subprocess
    import sys

    b = JigsawBoard()
    first, probe = tmp_path / "first.png", tmp_path / "probe.png"
    cv2.imwrite(str(first), b.render(0.0))
    cv2.imwrite(str(probe), b.render(8.0))
    req = {"id": 7, "cmd": "slide-step", "first": str(first), "probe": str(probe), "current": str(probe),
           "probe_s": 8, "s": 8, "goal": list(b.goal), "seed": list(b.centre()), "handle": list(b.handle()),
           "bounds": [-20, 300]}
    env = dict(os.environ, PYTHONPATH=os.pathsep.join([os.path.join(os.path.dirname(__file__), "..", "src"),
                                                        os.environ.get("PYTHONPATH", "")]))
    out = subprocess.run([sys.executable, "-m", "captchakraken.cli", "serve"], input=json.dumps(req) + "\n",
                         capture_output=True, text=True, timeout=60, env=env).stdout.splitlines()
    assert json.loads(out[0]) == {"ready": True}
    reply = json.loads(out[1])
    assert reply["id"] == 7 and reply["ok"], reply
    assert abs(reply["result"]["pos"][0] - b.centre(8)[0]) < 0.6 and reply["result"]["kind"] == "slide"
