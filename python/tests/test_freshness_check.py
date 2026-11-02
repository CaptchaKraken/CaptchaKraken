import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np

from captchakraken.image_processor import ImageProcessor
from captchakraken.keyframes import write_frame

SRC = str(Path(__file__).resolve().parents[1] / "src")


def _write(path: Path, arr: np.ndarray) -> str:
    write_frame(path, arr)
    return str(path)


def _frames(tmp_path):
    base = np.zeros((80, 80, 3), np.uint8)
    changed = base.copy()
    changed[:50, :50] = 255
    a = _write(tmp_path / "a.png", base)
    b = _write(tmp_path / "b.png", base.copy())
    c = _write(tmp_path / "c.png", changed)
    return a, b, c


def test_detect_movement_identical_vs_changed(tmp_path):
    a, b, c = _frames(tmp_path)
    assert ImageProcessor.detect_movement(a, b, 0.02) is False
    assert ImageProcessor.detect_movement(a, c, 0.02) is True


def test_detect_movement_resolution_change_is_movement(tmp_path):
    a = _write(tmp_path / "a.png", np.zeros((80, 80, 3), np.uint8))
    big = _write(tmp_path / "big.png", np.zeros((120, 120, 3), np.uint8))
    assert ImageProcessor.detect_movement(a, big, 0.02) is True


def test_serve_worker_check_movement(tmp_path):
    a, b, c = _frames(tmp_path)
    env = {**os.environ, "PYTHONPATH": SRC}
    proc = subprocess.Popen(
        [sys.executable, "-m", "captchakraken.cli", "serve"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, env=env,
    )
    try:
        assert json.loads(proc.stdout.readline())["ready"] is True

        def ask(id_, x, y):
            proc.stdin.write(json.dumps(
                {"id": id_, "cmd": "check-movement", "a": x, "b": y, "threshold": 0.02}
            ) + "\n")
            proc.stdin.flush()
            return json.loads(proc.stdout.readline())

        unchanged = ask(1, a, b)
        assert unchanged["ok"] is True
        assert unchanged["result"]["has_movement"] is False

        moved = ask(2, a, c)
        assert moved["ok"] is True
        assert moved["result"]["has_movement"] is True
    finally:
        proc.stdin.close()
        proc.wait(timeout=10)
