from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from captchakraken.page_solver import (
    PageSolver,
    PageSolverConfig,
    _GridSession,
)

GRID: List[List[int]] = [
    [0, 0, 100, 100], [100, 0, 200, 100], [200, 0, 300, 100],
    [0, 100, 100, 200], [100, 100, 200, 200], [200, 100, 300, 200],
    [0, 200, 100, 300], [100, 200, 200, 300], [200, 200, 300, 300],
]
ELEMENT_BOX = {"x": 0.0, "y": 0.0, "width": 300.0, "height": 300.0}
GRID_ARG = {"boxes": GRID, "size": 3, "screenshot_w": 300, "screenshot_h": 300}
CELL_5 = [0.4, 0.4, 0.6, 0.6]

CLICK_5 = {"action": "click", "target_bounding_boxes": [CELL_5]}
DONE = {"action": "done"}


class _FakeFrame:
    pass


class _FakeElement:
    def content_frame(self) -> _FakeFrame:
        return _FakeFrame()

    def bounding_box(self) -> Dict[str, float]:
        return dict(ELEMENT_BOX)


class _FakePage:
    pass


def _driver(states: Optional[Dict[str, List[int]]], answers: List[Dict[str, Any]]):
    solver = PageSolver(
        config=PageSolverConfig(
            recaptcha_fade_onset_grace_ms=60,
            recaptcha_dynamic_fade_poll_ms=1,
            recaptcha_dynamic_fade_wait_ms=20,
        ),
        solver=object(),
    )
    solver._solver = None
    solver._cursor_seeded = True

    log: Dict[str, Any] = {"rounds": 0, "clicked": [], "waits": 0, "submits": 0}

    def solution(_path: str, *_a: Any, **_k: Any):
        answer = answers[min(log["rounds"], len(answers) - 1)]
        log["rounds"] += 1
        return [answer], [{"total_tokens": 1}]

    def wait_loaded(*_a: Any) -> bool:
        log["waits"] += 1
        return True

    def submit(_page: Any, _button: Any) -> None:
        log["submits"] += 1

    solver._wait_for_grid_cells_loaded = lambda _el: True
    solver._screenshot = lambda *a, **k: None
    solver._grid_cell_states = lambda *_a: states
    solver._hover_cell = lambda *_a: None
    solver._frame_changed_since = lambda *_a: False
    solver._get_solution = solution
    solver._execute_click = (
        lambda _page, action, _box: log["clicked"].append(action["target_bounding_box"])
    )
    solver._wait_for_any_clicked_tile_loaded = wait_loaded
    solver._get_verify_button = lambda _frame: "verify"
    solver._move_and_click = submit
    return solver, log


def _session() -> _GridSession:
    return _GridSession(
        grid_boxes=GRID, element_box=dict(ELEMENT_BOX),
        scale_x=1.0, scale_y=1.0, screenshot_w=300, screenshot_h=300,
    )


def _solve(solver: PageSolver):
    return solver._solve_recaptcha_grid(
        _FakePage(), _FakeElement(), None, GRID_ARG, dict(ELEMENT_BOX)
    )


def test_a_chipped_tile_submits_without_a_second_inference():
    solver, log = _driver(
        {"empty": [], "changing": [5], "loaded": [1, 2, 3, 4, 6, 7, 8, 9], "selected": [5]},
        [CLICK_5, DONE],
    )
    performed, usage = _solve(solver)

    assert log["rounds"] == 1, "a ticked board must not be read a second time"
    assert log["clicked"] == [CELL_5]
    assert log["waits"] == 0, "nothing is being replaced, so there is nothing to wait for"
    assert log["submits"] == 1
    assert performed is True
    assert usage == [{"total_tokens": 1}]


def test_a_swapping_tile_still_costs_another_round():
    solver, log = _driver(
        {"empty": [5], "changing": [], "loaded": [1, 2, 3, 4, 6, 7, 8, 9], "selected": []},
        [CLICK_5, DONE],
    )
    performed, _ = _solve(solver)

    assert log["rounds"] == 2, "a replaced tile has to be read once it lands"
    assert log["waits"] == 1
    assert log["submits"] == 1
    assert performed is True


def test_one_chip_among_the_clicked_tiles_is_not_a_verdict():
    solver, _ = _driver(
        {"empty": [], "changing": [5, 6], "loaded": [], "selected": [5]}, [],
    )
    loading, chipped = solver._watch_clicked_tiles(
        _FakePage(), _FakeElement(), _session(), [5, 6]
    )
    assert chipped is False
    assert loading == [5, 6]


def test_a_chip_on_a_tile_we_did_not_click_is_not_a_verdict():
    solver, _ = _driver(
        {"empty": [], "changing": [], "loaded": [5], "selected": [2]}, [],
    )
    _, chipped = solver._watch_clicked_tiles(
        _FakePage(), _FakeElement(), _session(), [5]
    )
    assert chipped is False


def test_waiting_on_reloading_tiles_rests_on_one_and_moves_rarely():
    """Reaching for a different reloading tile on every 250 ms poll read as a cursor darting about the board."""
    solver, _log = _driver(None, [])
    hovered: List[int] = []
    solver._hover_cell = lambda _page, _session, cell: hovered.append(cell)
    hover = solver._hover_loop(_FakePage(), _session(), [4, 7, 9])
    for _ in range(20):
        hover()
    assert hovered == [4]


def test_a_rested_hand_drifts_a_few_pixels_and_stays_on_its_tile():
    solver, _log = _driver(None, [])
    moves: List[Any] = []
    solver._human.hovers = True
    solver._smooth_move = lambda _page, x, y: moves.append((x, y))
    solver._last_mouse = (150.0, 150.0)
    for _ in range(200):
        PageSolver._hover_cell(solver, _FakePage(), _session(), 5)
    assert all(100.0 < x < 200.0 and 100.0 < y < 200.0 for x, y in moves)
    assert max(abs(x - 150.0) + abs(y - 150.0) for x, y in moves) < 30.0


def test_two_points_in_one_tile_press_it_once():
    """A second press on a tile deselects it: live, round 2 clicked cells [1, 9, 9] and lost tile 9."""
    other_5 = [0.45, 0.42, 0.58, 0.55]
    solver, log = _driver(
        {"empty": [], "changing": [5], "loaded": [1, 2, 3, 4, 6, 7, 8, 9], "selected": [5]},
        [{"action": "click", "target_bounding_boxes": [CELL_5, other_5]}, DONE],
    )
    _solve(solver)
    assert log["clicked"] == [CELL_5]
