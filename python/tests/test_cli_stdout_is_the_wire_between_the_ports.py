"""Stdout is exactly one JSON document per invocation and refusals go to stderr with a non-zero exit, because the JS driver parses stdout as the answer."""

import json

import numpy as np
import pytest

from captchakraken import cli
from captchakraken.keyframes import write_frame


def _png(path, value=255, size=(80, 60)):
    img = np.full((size[1], size[0], 3), value, dtype=np.uint8)
    write_frame(path, img)
    return str(path)


def _run(monkeypatch, capsys, argv):
    monkeypatch.setattr("sys.argv", ["captchakraken", *argv])
    status = None
    try:
        cli.main()
    except SystemExit as e:
        status = e.code
    out, err = capsys.readouterr()
    return True, status, out, err


def test_identical_frames_report_no_movement(tmp_path, monkeypatch, capsys):
    a = _png(tmp_path / "a.png")
    b = _png(tmp_path / "b.png")

    handled, status, out, err = _run(
        monkeypatch, capsys, ["check-movement", a, b]
    )

    assert handled and status is None
    assert json.loads(out) == {"has_movement": False}


def test_a_changed_frame_reports_movement(tmp_path, monkeypatch, capsys):
    a = _png(tmp_path / "a.png", value=255)
    b = _png(tmp_path / "b.png", value=0)

    _, _, out, _ = _run(
        monkeypatch, capsys, ["check-movement", a, b]
    )

    assert json.loads(out) == {"has_movement": True}


def test_stdout_stays_empty_when_the_arguments_are_wrong(tmp_path, monkeypatch, capsys):
    handled, status, out, err = _run(
        monkeypatch, capsys, ["check-movement", "only-one.png"]
    )

    assert status == 1, "a usage error must exit non-zero"
    assert out == "", f"usage text reached stdout: {out!r}"
    assert json.loads(err)["error"].startswith("Usage:")


def test_a_missing_image_is_refused_on_stderr_with_a_non_zero_exit(tmp_path, monkeypatch, capsys):
    handled, status, out, err = _run(
        monkeypatch, capsys, ["find-checkbox", str(tmp_path / "absent.png")],
    )

    assert status == 1
    assert out == ""
    assert "Image not found" in json.loads(err)["error"]


def test_a_readable_image_answers_with_one_json_document(tmp_path, monkeypatch, capsys):
    handled, status, out, err = _run(
        monkeypatch, capsys, ["find-checkbox", _png(tmp_path / "p.png")]
    )

    assert handled and status is None
    assert json.loads(out) is None
    assert out.count("\n") == 1, "more than one line reached stdout"


def test_an_unparseable_threshold_falls_back_instead_of_crashing(tmp_path, monkeypatch, capsys):
    a = _png(tmp_path / "a.png")
    b = _png(tmp_path / "b.png")

    handled, status, out, err = _run(
        monkeypatch, capsys, ["check-movement", a, b, "not-a-number"],
    )

    assert status is None
    assert json.loads(out) == {"has_movement": False}
