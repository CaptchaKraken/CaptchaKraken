"""Prompt generation 3: one model, one prompt for every puzzle, one answer shape, and `refresh` for a board a person
would not solve. Mirror of `js/src/one-prompt-answers-every-puzzle.test.ts`, which holds the driver half; the prompt,
the parser and the grid live only here because the JS port asks the engine.
"""

from __future__ import annotations

import json
import re
from contextlib import contextmanager
from pathlib import Path
from typing import Any, List

import pytest

from captchakraken import prompts
from captchakraken.action_types import ClickAction, DoneAction, DragAction, HoldAction, RefreshAction, TypeAction
from captchakraken.kinds import ActionKind, PixelAnswerKind, Vendor
from captchakraken.page_solver import PageSolver
from captchakraken.planner import ActionPlanner
from captchakraken.selectors import REFRESH_SELECTORS, SELECTORS
from captchakraken.solver import CaptchaSolver, UnsupportedCaptchaError
from fake_dom import FakeNode, fake_scope

ROOT = Path(__file__).resolve().parents[2]

REGISTRY = {
    "latest": "Acme/Two",
    "models": {
        "Acme/Two": {"prompt_version": "2", "lora_name": "two"},
        "Acme/Three": {"prompt_version": "3", "lora_name": "three",
                       "experts": {"grid": "three-grid", "pixel": "three-general"}},
    },
    "served_aliases": {"three": "Acme/Three", "two": "Acme/Two"},
}


@pytest.fixture
def registry(monkeypatch):
    prompts.clear_cache()
    monkeypatch.setattr(prompts, "_load_registry", lambda: json.loads(json.dumps(REGISTRY)))
    yield
    prompts.clear_cache()


# ── the prompt ───────────────────────────────────────────────────────────


def test_generation_3_is_one_prompt_and_the_older_generations_are_untouched():
    three = prompts.builtin("3")
    assert three.general == prompts.BUILTIN_PROMPTS["3"]["general"]
    assert set(prompts.BUILTIN_PROMPTS["3"]) == {"general"}
    for version in ("1", "2"):
        assert prompts.builtin(version).general is None
        assert set(prompts.BUILTIN_PROMPTS[version]) == {"action_pixel", "grid", "video", "text"}


def test_the_general_prompt_names_every_verb_the_parser_reads():
    general = prompts.builtin("3").general
    for verb in ("click", "drag", "hold", "type", "refresh"):
        assert f'"action": "{verb}"' in general


def test_a_family_prompt_asked_of_generation_3_says_why_it_has_none():
    three = prompts.builtin("3")
    for ask in (three.pixel_prompt, three.text_prompt, lambda: three.grid_prompt(rows=3, cols=3)):
        with pytest.raises(ValueError, match="one general prompt"):
            ask()


def test_an_animated_board_on_generation_3_is_refused_not_sent_as_keyframes():
    with pytest.raises(ValueError, match="frame-numbered video"):
        prompts.builtin("3").video_prompt(4)


# ── one model, nothing routed ────────────────────────────────────────────


def test_a_generation_3_model_routes_nowhere_even_when_it_declares_experts(registry, capsys):
    assert prompts.experts("three") == {}
    assert "never routed to" in capsys.readouterr().err
    for family in ("grid", "pixel", "video", "text", None):
        assert prompts.route("three", family) == "three"
    with pytest.raises(ValueError, match="declares no experts"):
        prompts.route("three", "grid", pin="grid")


def _planner(model: str, sent: List[Any]) -> ActionPlanner:
    p = ActionPlanner(model=model, base_url="http://127.0.0.1:9/v1", api_key="k")

    def chat(prompt, image_path, max_tokens=512, family=None):
        sent.append((prompt, p._model_for(family)))
        return '{"action": "click", "points": [[500, 500]]}'

    p._chat_with_image = chat
    return p


def test_every_still_on_generation_3_sends_the_general_prompt_to_the_one_model(registry):
    sent: List[Any] = []
    p = _planner("three", sent)
    p.get_pixel_actions("x.png")
    p.get_pixel_actions("x.png", text_mode=True)
    assert sent == [(prompts.builtin("3").general, "three")] * 2


def test_generation_2_still_asks_its_family_prompts(registry):
    sent: List[Any] = []
    p = _planner("two", sent)
    p.get_pixel_actions("x.png")
    p.get_pixel_actions("x.png", text_mode=True)
    two = prompts.builtin("2")
    assert [s[0] for s in sent] == [two.action_prompt, two.text_template]


# ── the answer ───────────────────────────────────────────────────────────


@pytest.mark.parametrize("answer,parsed", [
    ({"action": "click", "points": [[100, 200], [300, 400]], "ids": [2, 5]},
     [{"kind": PixelAnswerKind.CLICK, "points": [(0.1, 0.2), (0.3, 0.4)], "ids": [2, 5]}]),
    ({"action": "click", "points": []}, [{"kind": PixelAnswerKind.CLICK, "points": [], "ids": []}]),
    ({"action": "refresh", "points": [[70, 930]]}, [{"kind": PixelAnswerKind.REFRESH, "points": [(0.07, 0.93)]}]),
    ({"action": "refresh", "points": []}, [{"kind": PixelAnswerKind.REFRESH, "points": []}]),
    ({"action": "drag", "drags": [{"from": [100, 100], "to": [900, 900], "from_id": 1, "to_id": 2}]},
     [{"kind": PixelAnswerKind.DRAG, "src": (0.1, 0.1), "dst": (0.9, 0.9)}]),
    ({"action": "drag", "drags": [{"to": [600, 400]}]}, [{"kind": PixelAnswerKind.SLIDE, "dst": (0.6, 0.4)}]),
    ({"action": "hold", "points": [[500, 520]], "ids": [1]}, [{"kind": PixelAnswerKind.HOLD, "points": [(0.5, 0.52)]}]),
    ({"action": "type", "text": "aB3x"}, [{"kind": PixelAnswerKind.TYPE, "text": "aB3x"}]),
    ({"frame": 3, "action": "click", "points": [[500, 500]]},
     [{"kind": PixelAnswerKind.CLICK, "points": [(0.5, 0.5)], "ids": []}]),
    ("not json", []),
])
def test_one_parser_reads_every_generation_3_answer(answer, parsed):
    assert ActionPlanner._normalize_general(answer) == parsed


def test_parsed_answers_become_the_driver_actions():
    out = CaptchaSolver._to_actions(object(), [
        {"kind": PixelAnswerKind.CLICK, "points": [], "ids": []},
        {"kind": PixelAnswerKind.REFRESH, "points": [(0.07, 0.93)]},
        {"kind": PixelAnswerKind.REFRESH, "points": []},
        {"kind": PixelAnswerKind.DRAG, "src": (0.1, 0.1), "dst": (0.9, 0.9)},
        {"kind": PixelAnswerKind.HOLD, "points": [(0.5, 0.5)]},
        {"kind": PixelAnswerKind.TYPE, "text": "aB3x"},
    ])
    assert [type(a) for a in out] == [DoneAction, RefreshAction, RefreshAction, DragAction, HoldAction, TypeAction]
    x1, y1, x2, y2 = out[1].target_bounding_box
    assert abs((x1 + x2) / 2 - 0.07) < 1e-9 and abs((y1 + y2) / 2 - 0.93) < 1e-9
    assert out[2].target_bounding_box is None


def test_an_animated_board_on_generation_3_is_an_unsupported_puzzle_not_a_crash(registry, tmp_path):
    from PIL import Image

    frame = tmp_path / "f1.png"
    Image.new("RGB", (40, 40)).save(frame)
    solver = CaptchaSolver(model="three", api_key="k")
    with pytest.raises(UnsupportedCaptchaError, match="frame-numbered video"):
        solver.solve_keyframes([str(frame)])


# ── a grid on generation 3 ───────────────────────────────────────────────

BOXES = [(c * 100, r * 100, c * 100 + 100, r * 100 + 100) for r in range(3) for c in range(3)]


def _grid_solver(monkeypatch, answer: str, *, selected=(), loading=()):
    from captchakraken import solver as solver_module

    monkeypatch.setattr(solver_module, "detect_selected_cells", lambda path, boxes: (list(selected), list(loading)))
    monkeypatch.setattr(solver_module, "get_numbered_grid_overlay", lambda path, boxes, output_path: output_path)
    s = CaptchaSolver.__new__(CaptchaSolver)
    s._temp_files, s._image_size = [], (300, 300)
    s.planner = type("P", (), {})()
    s.planner.prompts = prompts.builtin("3")
    s.planner.get_general_actions = lambda path: ActionPlanner._normalize_general(json.loads(answer))
    s.planner.get_grid_selection = lambda *a, **k: pytest.fail("generation 3 never asks the grid prompt")
    return s


def _clicked(action) -> List[int]:
    centres = [((x1 + x2) / 2 * 300, (y1 + y2) / 2 * 300) for (x1, y1, x2, y2) in action.target_bounding_boxes]
    return [next(i + 1 for i, (a, b, c, d) in enumerate(BOXES) if a <= x <= c and b <= y <= d) for x, y in centres]


def test_a_grid_answer_is_read_by_its_ids(monkeypatch):
    s = _grid_solver(monkeypatch, '{"action": "click", "points": [[50, 50]], "ids": [3, 7]}')
    assert _clicked(s._solve_grid("b.png", BOXES, 3, 3)) == [3, 7]


def test_a_grid_answer_without_ids_is_read_by_where_its_points_land(monkeypatch):
    s = _grid_solver(monkeypatch, '{"action": "click", "points": [[833, 166], [500, 500], [500, 500]]}')
    assert _clicked(s._solve_grid("b.png", BOXES, 3, 3)) == [3, 5]


def test_an_id_that_is_no_cell_falls_back_to_the_points(monkeypatch):
    s = _grid_solver(monkeypatch, '{"action": "click", "points": [[166, 833]], "ids": [12]}')
    assert _clicked(s._solve_grid("b.png", BOXES, 3, 3)) == [7]


def test_selected_and_loading_cells_are_still_left_alone(monkeypatch):
    s = _grid_solver(monkeypatch, '{"action": "click", "points": [], "ids": [1, 2, 3]}', selected=[1], loading=[2])
    assert _clicked(s._solve_grid("b.png", BOXES, 3, 3)) == [3]
    s = _grid_solver(monkeypatch, '{"action": "click", "points": [], "ids": [2]}', loading=[2])
    assert s._solve_grid("b.png", BOXES, 3, 3).action == ActionKind.WAIT


def test_nothing_matching_on_a_grid_submits_it(monkeypatch):
    s = _grid_solver(monkeypatch, '{"action": "click", "points": []}')
    assert isinstance(s._solve_grid("b.png", BOXES, 3, 3), DoneAction)


def test_a_refresh_on_a_grid_is_passed_to_the_driver(monkeypatch):
    s = _grid_solver(monkeypatch, '{"action": "refresh", "points": [[90, 960]]}')
    (action,) = s._solve_grid("b.png", BOXES, 3, 3)
    assert isinstance(action, RefreshAction)


def test_an_unreadable_grid_answer_is_unsupported_not_an_empty_selection(monkeypatch):
    s = _grid_solver(monkeypatch, '"nonsense"')
    with pytest.raises(UnsupportedCaptchaError):
        s._solve_grid("b.png", BOXES, 3, 3)


# ── performing a refresh ─────────────────────────────────────────────────


class _Mouse:
    def __init__(self) -> None:
        self.at: List[Any] = []

    def move(self, x, y) -> None:
        self.at.append((round(x), round(y)))

    def down(self) -> None:
        pass

    def up(self) -> None:
        pass


class _Page:
    def __init__(self) -> None:
        self.mouse = _Mouse()
        self.viewport_size = {"width": 800, "height": 600}


def _driver(monkeypatch) -> PageSolver:
    from captchakraken import humanize
    from captchakraken.humanize import NullHumanizer

    monkeypatch.setattr(humanize, "_delay", lambda ms: None)
    s = PageSolver.__new__(PageSolver)
    s._human = NullHumanizer()
    s._acted_on_board = False

    @contextmanager
    def gesture():
        yield

    s._gesture = gesture
    return s


BOX = {"x": 0, "y": 0, "width": 400, "height": 400}
AT_ARROW = {"action": ActionKind.REFRESH, "target_bounding_box": [0.09, 0.89, 0.11, 0.91]}


def test_the_vendors_own_control_is_pressed_first(monkeypatch):
    s, page = _driver(monkeypatch), _Page()
    control = FakeNode(["#recaptcha-reload-button"], box={"x": 300, "y": 300, "width": 20, "height": 20})
    assert s._execute_refresh(page, fake_scope([control]), AT_ARROW, BOX) is True
    x, y = page.mouse.at[-1]
    assert 300 <= x <= 320 and 300 <= y <= 320, "pressed the control, not the model's point"


def test_without_a_control_the_models_point_is_pressed(monkeypatch):
    s, page = _driver(monkeypatch), _Page()
    assert s._execute_refresh(page, fake_scope([]), AT_ARROW, BOX) is True
    x, y = page.mouse.at[-1]
    assert 35 <= x <= 45 and 355 <= y <= 365


def test_with_neither_the_round_ends_having_done_nothing(monkeypatch):
    s, page = _driver(monkeypatch), _Page()
    assert s._execute_refresh(page, fake_scope([]), {"action": ActionKind.REFRESH}, BOX) is False
    assert page.mouse.at == []


def test_a_second_refresh_is_a_second_board_not_a_repeated_answer(monkeypatch):
    s = PageSolver.__new__(PageSolver)
    s._last_answer_sig, s._no_progress_rounds = None, 0
    refresh = [RefreshAction(action=ActionKind.REFRESH, target_bounding_box=[0.09, 0.89, 0.11, 0.91])]
    assert s._note_answer(refresh, None) is False
    assert s._note_answer(refresh, None) is False
    assert s._no_progress_rounds == 0
    click = [ClickAction(action=ActionKind.CLICK, target_bounding_boxes=[[0.4, 0.4, 0.6, 0.6]])]
    monkeypatch.setattr(s, "_apply_sampling", lambda: None, raising=False)
    monkeypatch.setattr(s, "_invalidate_animated_answer", lambda: None, raising=False)
    monkeypatch.setattr(s, "_arm_animated_probe", lambda: None, raising=False)
    s._resample_level = 0
    assert s._note_answer(click, None) is False
    assert s._note_answer(click, None) is True, "an ordinary repeated answer is still caught"


# ── the two ports' tables ────────────────────────────────────────────────


def _js_rows(field: str) -> dict:
    """{vendor value: [selectors]} for one list field of js/src/selectors.ts."""
    src = (ROOT / "js" / "src" / "selectors.ts").read_text()
    rows = re.findall(r"\[Vendor\.([A-Z]+)\]: \{(.*?)\n  \}", src, re.S)
    out = {}
    for name, body in rows:
        m = re.search(rf"\n    {field}: \[(.*?)\],", body, re.S)
        out[Vendor[name].value] = re.findall(r"'([^']*)'", m.group(1)) if m else []
    return out


def test_both_ports_press_the_same_refresh_controls():
    js = {v: sels for v, sels in _js_rows("refresh").items() if sels}
    assert js == {v.value: list(s.refresh) for v, s in SELECTORS.items() if s.refresh}
    assert REFRESH_SELECTORS, "no vendor names a refresh control"


def test_both_ports_find_the_press_and_hold_widget():
    assert list(SELECTORS[Vendor.HUMAN].widget) == _js_rows("widget")["human"] == ["#px-captcha"]


def test_the_press_and_hold_widget_is_found_by_its_container():
    from captchakraken.page_solver import PageSolverConfig

    widget = PageSolver(config=PageSolverConfig()).detect_captcha(fake_scope([FakeNode(["#px-captcha"])]))
    assert widget.vendor == Vendor.HUMAN
