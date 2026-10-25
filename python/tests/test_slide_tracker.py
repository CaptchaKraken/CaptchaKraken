"""The slide tracker against boards drawn here: a jigsaw piece on a track, a disc that turns in place, and a piece
carried by the pointer itself. Every board has a handle and a filled track that move too, and most have a badge
animating elsewhere, because those are what a diff-based tracker used to mistake for the piece."""

import math

import cv2
import numpy as np
import pytest
from slide_boards import CarriedBoard, DiscBoard, JigsawBoard

from captchakraken.tool_calls import slide_tracker as st


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


def _framed(ratio):
    """The piece resting just above the track with only flat white between, as on GeeTest: dense flow smears across
    the strip and joins the piece to the knob below it, though no pixel there changed."""
    return JigsawBoard(ratio=ratio, y0=110, picture_ends=130)


@pytest.mark.parametrize("ratio", [0.8, 1.0, 1.27])
def test_a_piece_joined_to_the_knob_by_flat_ground_is_still_its_own_body(ratio):
    b = _framed(ratio)
    seg = st.segment(b.render(0), b.render(8), seed=b.centre(), handle=b.handle())
    hx, hy = b.handle()
    assert not seg.grabbed, "the knob came with the piece, so the driver would steer the piece as if it held it"
    assert not seg.mask[int(hy) - 14:int(hy) + 14].any(), "the mask reaches into the track"
    assert seg.probe[1] == pytest.approx(8 * ratio, abs=0.3)


@pytest.mark.parametrize("ratio", [0.8, 1.0, 1.27])
def test_without_a_seed_a_piece_joined_to_the_knob_is_still_found(ratio):
    b = _framed(ratio)
    seg = st.segment(b.render(0), b.render(8), seed=None, handle=b.handle())
    cx, cy = seg.centroid
    px, py = b.centre()
    hy = b.handle()[1]
    # The shadow travels with the piece, so it is part of the body and pulls its centroid toward the shadow's side.
    assert abs(cx - px) < 8 and abs(cy - py) < 8 and not seg.grabbed
    assert not seg.mask[int(hy) - 14:int(hy) + 14].any(), "the mask reaches into the track"


@pytest.mark.parametrize("ratio", [0.8, 1.27])
def test_the_loop_seats_a_piece_framed_above_flat_ground(ratio):
    b = _framed(ratio)
    s, _, reply = _drive(b, b.centre(), (b.goal[0], b.centre()[1]))
    assert abs(b.centre(s)[0] - b.goal[0]) <= 2.0 and reply["done"]


@pytest.mark.parametrize("ratio", [0.8, 1.0, 1.27])
def test_flat_ground_the_probe_cannot_tell_from_the_piece_is_not_matched_as_the_piece(ratio):
    """At rest the piece sits on flat sky with flat dark ground ahead of it. Moved 8 px, the piece and that ground
    draw the same probe whether the ground moved or not, so the mask may hold some; matched against a shot of the
    piece over the slot's texture, that ground is a template the piece no longer carries, and on Yidun it lost the
    piece (correlation 0.51 at its true place)."""
    b = JigsawBoard(ratio=ratio, flat_rest=True)
    seg = st.segment(b.render(0), b.render(8), seed=b.centre(), handle=b.handle())
    s = (b.slot[0] - b.x0) / ratio - 6
    params, corr = st.measure(b.render(0), b.render(s), seg, guess=(0.0, ratio * s, 0.0))
    assert params[1] == pytest.approx(ratio * s, abs=0.5) and abs(params[2]) < 0.5
    # Not 1: the soft shadow travels with the piece but darkens whatever ground it is over.
    assert corr > 0.75


@pytest.mark.parametrize("ratio", [0.8, 1.27])
def test_the_loop_seats_a_piece_resting_on_flat_ground(ratio):
    b = JigsawBoard(ratio=ratio, flat_rest=True)
    s, _, reply = _drive(b, b.centre(), (b.goal[0], b.centre()[1]))
    assert abs(b.centre(s)[0] - b.goal[0]) <= 2.0 and reply["done"]


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
