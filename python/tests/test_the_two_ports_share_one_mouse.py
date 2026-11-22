"""Both drivers draw the mouse from myuri's same seeded stream, so a seed gives the same path in both and the parity is
pinned exactly: myuri's plan, our taming and densifying, and each speed's settings.

The fixture is recorded from the JS port (`node js/scripts/record-mouse-cross-port.cjs`, after `npm run build`) because
Tier 1 has no node. Never re-record it to make a failure go away: a failure here means the two drivers started moving
differently.
"""
import json
import re
from pathlib import Path

import pytest

from captchakraken.humanize import Motion, trajectory

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "myuri_cross_port.json"

# Far looser than libm residue between the ports, far tighter than a diverged random stream.
_TOL = 1e-6

CASES = json.loads(FIXTURE.read_text())


def _snake(settings):
    """myuri's JS settings are camelCase and its Python ones snake_case; the values are the same."""
    if not isinstance(settings, dict):
        return settings
    return {re.sub(r"(?<!^)(?=[A-Z])", "_", k).lower(): _snake(v) for k, v in settings.items()}


def _motion(case):
    return Motion(_snake(case.get("settings")), seed=case["seed"], speed=case["speed"])


@pytest.mark.parametrize("case", CASES, ids=[f"seed{c['seed']}-{c['speed']}" for c in CASES])
def test_python_reproduces_the_js_trajectory(case):
    points, timings = trajectory(tuple(case["from"]), tuple(case["to"]), _motion(case))
    assert len(points) == len(case["points"]), "a different sample count is a diverged random stream, not rounding"
    for i, ((x, y), (jx, jy)) in enumerate(zip(points, case["points"])):
        assert abs(x - jx) < _TOL and abs(y - jy) < _TOL, f"sample {i}: python ({x}, {y}) vs js ({jx}, {jy})"
    for i, (t, jt) in enumerate(zip(timings, case["timings"])):
        assert abs(t - jt) < _TOL, f"sample {i}: python {t} ms vs js {jt} ms"


def test_a_seed_is_reproducible_within_one_port():
    assert trajectory((10, 10), (700, 400), Motion(seed=99)) == trajectory((10, 10), (700, 400), Motion(seed=99))


def test_no_seed_means_a_fresh_path_every_time():
    assert trajectory((10, 10), (700, 400))[0] != trajectory((10, 10), (700, 400))[0]


def test_the_endpoints_are_exact():
    for seed in (1, 2, 3):
        pts, _ = trajectory((123.5, 77.25), (812.75, 455.5), Motion(seed=seed))
        assert tuple(pts[0]) == (123.5, 77.25) and tuple(pts[-1]) == (812.75, 455.5)
