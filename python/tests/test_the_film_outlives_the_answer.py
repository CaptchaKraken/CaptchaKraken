# One burst can only show the model the screens that fell inside its window — measured, a 4s burst against a 5.3s cycle showed
# two screens of three — and the answer it produces is identical next round by construction, because sampling is greedy over the
# same frames. So a refused animated answer was re-pressed until the no-progress fence tripped, three rounds in, with half the
# solve budget unspent. Measured live 2026-09-15: hCaptcha's animated board read 2/15 and 6/12 on the two served models.
#
# The film now accumulates for the whole solve, so every round asks against strictly more of the board than the last ask saw.
# The JS port films CONTINUOUSLY, through inference and the verdict wait; sync Playwright is thread-affine, so this port films
# another chunk per round instead. Different density, same contract — which is what these pin.
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from captchakraken import page_solver
from captchakraken.page_solver import PageSolver, PageSolverConfig
from virtual_clock import install

_SCREENS = [b"screen-A" + b"\x00" * 64, b"screen-B" + b"\x11" * 64, b"screen-C" + b"\x22" * 64]


def _solver(monkeypatch):
    """A solver filming a 3-screen cycle, with the slicer stubbed: this is about WHAT is sliced, not how."""
    import numpy as np

    install(monkeypatch, page_solver)
    solver = PageSolver(config=PageSolverConfig())
    solver._reset_animated_state()
    solver._deadline_ms = None
    sliced: list = []
    shots = {"n": 0}

    def fake_shot(element, path, animations="allow", timeout_ms=None):
        with open(path, "wb") as fh:
            fh.write(_SCREENS[shots["n"] % len(_SCREENS)])
        shots["n"] += 1

    def fake_slice(frames, burst_ms):
        sliced.append(len(frames))
        return ["/tmp/ck_fake_keyframe.png"], "/tmp/ck_fake_dir"

    monkeypatch.setattr(solver, "_screenshot", fake_shot)
    monkeypatch.setattr(solver, "_slice", fake_slice)
    monkeypatch.setattr("captchakraken.keyframes.read_frame", lambda p: np.zeros((4, 4, 3), dtype=np.uint8))
    return solver, sliced


def test_a_second_round_slices_everything_filmed_so_far(monkeypatch):
    solver, sliced = _solver(monkeypatch)
    solver._record_keyframes(object())
    first_film = len(solver._film_frames)
    solver._record_keyframes(object())

    assert len(sliced) == 2
    # Against the accumulated film, not against the first slice: the two bursts do not film the same number
    # of frames (the second starts at a different phase of the cycle, so it closes at a different point), and
    # `sliced[1] > sliced[0]` is true by accident even when the first film is thrown away.
    assert sliced[1] == len(solver._film_frames), (
        f"the second round sliced {sliced[1]} frames while the film holds {len(solver._film_frames)} — it "
        f"sliced only its own burst, so the re-ask is the same question and the answer will be the same")
    assert sliced[0] == first_film
    assert len(solver._film_frames) > first_film, "the second round filmed nothing new"


def test_the_film_dies_with_the_board_not_with_the_answer(monkeypatch):
    solver, _ = _solver(monkeypatch)
    solver._record_keyframes(object())
    filmed = len(solver._film_frames)
    assert filmed, "nothing was filmed"

    # A refused answer: the answer is spent, the film is the only thing that can improve the next question.
    solver._discard_animated_plan()
    assert len(solver._film_frames) == filmed, "a refused answer threw away the film that outlives it"

    # A board that is gone: its film can never describe the next one.
    solver._stop_animated_film()
    assert solver._film_frames == [], "the film of a board that is gone was kept"
    assert solver._film_ms == 0.0


def test_a_new_solve_films_a_new_board(monkeypatch):
    solver, _ = _solver(monkeypatch)
    solver._record_keyframes(object())
    assert solver._film_frames, "nothing was filmed"
    solver._reset_animated_state()
    assert solver._film_frames == [], (
        "a film leaking into the next captcha would answer it with pictures of the previous one")


def test_the_js_port_also_keeps_filming():
    js = (Path(__file__).resolve().parents[2] / "js" / "src" / "solver.ts").read_text()
    assert "private animatedFilm" in js, (
        "the JS port has no camera outliving a round, so a refused animated answer there is still re-pressed")
    assert "this.invalidateAnimatedAnswer();" in js, (
        "the JS port keeps a refused animated answer, which hands the no-progress fence the same signature "
        "three rounds running while this port re-asks")
    assert "await film.snapshot()" in js, (
        "the JS port re-asks a refused answer on the SAME frames, so the question does not change and "
        "neither does the answer; this port re-slices a film that has grown")
    assert "await this.ph(Phase.BURST, () => film.settledOrCycled());" in js, (
        "the JS port re-slices the instant the answer is refused, so the film it cuts holds nothing of the "
        "board now on screen; both ports wait for that board to show itself first")


def _reshuffling(monkeypatch):
    """A board that deals a fresh set of screens the moment its answer is refused."""
    import numpy as np

    install(monkeypatch, page_solver)
    solver = PageSolver(config=PageSolverConfig())
    solver._reset_animated_state()
    solver._deadline_ms = None
    sliced: list = []
    state = {"n": 0, "board": 0}

    def fake_shot(element, path, animations="allow", timeout_ms=None):
        screen = _SCREENS[state["n"] % len(_SCREENS)]
        with open(path, "wb") as fh:
            fh.write(bytes([state["board"]]) + screen)
        state["n"] += 1

    monkeypatch.setattr(solver, "_screenshot", fake_shot)
    monkeypatch.setattr(solver, "_slice", lambda frames, ms: (sliced.append(len(frames)), (["/tmp/k.png"], "/tmp/d"))[1])
    monkeypatch.setattr("captchakraken.keyframes.read_frame", lambda p: np.zeros((4, 4, 3), dtype=np.uint8))
    return solver, sliced, state


def test_the_film_restarts_on_the_board_that_is_actually_there(monkeypatch):
    # ONE FILM, ONE BOARD. GeeTest's svg board reshuffles its candidates every time it refuses an answer, and
    # keyframes cut across both states describe neither: six picks over six screens where the board only ever
    # shows three, `_detect_cycle` giving up on the extra states, and the frame the model names being one the
    # widget will never show again — so the click waits out the whole keyframe_wait_timeout_ms for a picture
    # that is gone. Measured on the gate, that board ran 0/3 here and took 12s a round doing it.
    solver, sliced, state = _reshuffling(monkeypatch)
    solver._record_keyframes(object())
    first = len(solver._film_frames)
    assert first, "nothing was filmed"

    state["board"] = 1                      # the answer was refused and the vendor dealt a new puzzle
    solver._record_keyframes(object())

    assert sliced[1] == len(solver._film_frames)
    assert len(solver._film_frames) < first + sliced[0], (
        f"the film still holds {len(solver._film_frames)} frames across two boards; the {first} filmed of a "
        f"board the vendor has replaced can only name screens the widget will never show again")
    assert solver._film_digests, "the restarted film kept no screens to check the next round against"


def test_a_board_that_came_back_keeps_its_whole_film(monkeypatch):
    # The restart is not a reset: this is the case filming on exists for, and restarting every round would
    # throw away exactly the extra screens that give a refused answer a different one to give.
    solver, sliced, _state = _reshuffling(monkeypatch)
    solver._record_keyframes(object())
    first = len(solver._film_frames)
    solver._record_keyframes(object())

    assert len(solver._film_frames) > first, (
        "a board whose screens kept coming back was never replaced, so its film is kept and added to")
    assert sliced[1] == len(solver._film_frames)


def test_a_board_that_never_repeats_keeps_its_film_and_is_not_refilmed(monkeypatch):
    # hCaptcha's continuous animations never show the same screen twice, so "a screen the film holds came
    # back" can never be proved for them. Restarting on the ABSENCE of that proof threw the film away every
    # round and spent a full ceiling-long window rebuilding it: measured on the gate, boards at 54.6s and
    # 59.1s against a 49s ceiling. A replacement has to be PROVED, not assumed.
    import numpy as np

    install(monkeypatch, page_solver)
    cfg = PageSolverConfig()
    solver = PageSolver(config=cfg)
    solver._reset_animated_state()
    solver._deadline_ms = None
    sliced: list = []
    n = {"i": 0}

    def fake_shot(element, path, animations="allow", timeout_ms=None):
        with open(path, "wb") as fh:
            fh.write(b"unique-%d" % n["i"])
        n["i"] += 1

    monkeypatch.setattr(solver, "_screenshot", fake_shot)
    monkeypatch.setattr(solver, "_slice",
                        lambda frames, ms: (sliced.append(len(frames)), (["/tmp/k.png"], "/tmp/d"))[1])
    monkeypatch.setattr("captchakraken.keyframes.read_frame", lambda p: np.zeros((4, 4, 3), dtype=np.uint8))

    solver._record_keyframes(object())
    first, first_ms = len(solver._film_frames), solver._film_ms
    assert first_ms >= cfg.video_burst_max_ms * 0.9, (
        f"a board that never repeats never settles and never cycles, so the first window runs to the "
        f"{cfg.video_burst_max_ms}ms ceiling; this one stopped at {first_ms:.0f}ms")

    solver._record_keyframes(object())

    assert len(solver._film_frames) > first, (
        "a board that never repeats a screen has not been replaced, it has simply never repeated; throwing "
        "its film away leaves the re-ask with less of the board than the ask that was refused")
    assert sliced[1] == len(solver._film_frames)
    reask_ms = solver._film_ms - first_ms
    assert reask_ms < cfg.video_burst_max_ms * 0.75, (
        f"the re-ask filmed another {reask_ms:.0f}ms out of a {cfg.video_burst_max_ms}ms ceiling, waiting "
        f"for a cycle this board is never going to close")
