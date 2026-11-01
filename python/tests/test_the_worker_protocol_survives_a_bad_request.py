"""A bad line must be answered and the worker must live on: dying mid-solve leaves the mouse pressed."""

import io
import json

import numpy as np
import pytest

from captchakraken import cli
from captchakraken.keyframes import write_frame


def _png(path, value=255, size=(60, 40)):
    write_frame(path, np.full((size[1], size[0], 3), value, dtype=np.uint8))
    return str(path)


def _serve(monkeypatch, capsys, lines):
    monkeypatch.setattr("sys.argv", ["captchakraken", "serve"])
    monkeypatch.setattr("sys.stdin", io.StringIO("".join(f"{l}\n" for l in lines)))
    cli.main()
    out = capsys.readouterr().out.strip().split("\n")
    return [json.loads(l) for l in out if l]


def test_it_announces_readiness_before_reading_a_request(monkeypatch, capsys):
    replies = _serve(monkeypatch, capsys, [])
    assert replies == [{"ready": True}], "the worker must say ready even with no work"


def test_every_answer_carries_the_id_it_was_asked_with(monkeypatch, capsys, tmp_path):
    a = _png(tmp_path / "a.png")
    b = _png(tmp_path / "b.png")
    replies = _serve(monkeypatch, capsys, [
        json.dumps({"id": 11, "cmd": "check-movement", "a": a, "b": b}),
        json.dumps({"id": 12, "cmd": "check-movement", "a": a, "b": b}),
    ])

    assert replies[0] == {"ready": True}
    assert [r["id"] for r in replies[1:]] == [11, 12]
    assert all(r["ok"] for r in replies[1:])


def test_a_malformed_line_is_answered_and_the_worker_keeps_going(monkeypatch, capsys, tmp_path):
    a = _png(tmp_path / "a.png")
    b = _png(tmp_path / "b.png")
    replies = _serve(monkeypatch, capsys, [
        "{not json at all",
        json.dumps({"id": 2, "cmd": "check-movement", "a": a, "b": b}),
    ])

    assert replies[1]["ok"] is False, "a malformed line must be answered, not ignored"
    assert replies[1]["error"]
    assert replies[2]["id"] == 2 and replies[2]["ok"] is True, \
        "the worker died on a bad line instead of serving the next request"
    assert replies[2]["result"]["has_movement"] is False


def test_an_unknown_command_is_refused_by_name_without_dying(monkeypatch, capsys, tmp_path):
    a = _png(tmp_path / "a.png")
    replies = _serve(monkeypatch, capsys, [
        json.dumps({"id": 1, "cmd": "polish-the-brass"}),
        json.dumps({"id": 2, "cmd": "check-movement", "a": a, "b": a}),
    ])

    assert replies[1] == {"id": 1, "ok": False, "error": "unknown cmd: 'polish-the-brass'"}
    assert replies[2]["ok"] is True


def test_a_request_missing_an_argument_fails_only_that_request(monkeypatch, capsys, tmp_path):
    a = _png(tmp_path / "a.png")
    replies = _serve(monkeypatch, capsys, [
        json.dumps({"id": 1, "cmd": "check-movement"}),
        json.dumps({"id": 2, "cmd": "check-movement", "a": a, "b": a}),
    ])

    assert replies[1]["ok"] is False and replies[1]["id"] == 1
    assert replies[2]["ok"] is True


def test_blank_lines_are_skipped_rather_than_answered(monkeypatch, capsys):
    replies = _serve(monkeypatch, capsys, ["", "   ", ""])
    assert replies == [{"ready": True}]


def test_the_wait_gate_answers_a_match_for_an_unchanged_region(monkeypatch, capsys, tmp_path):
    ref = _png(tmp_path / "ref.png", value=120)
    live = _png(tmp_path / "live.png", value=120)
    replies = _serve(monkeypatch, capsys, [
        json.dumps({"id": 1, "cmd": "match-region", "ref": ref, "live": live,
                    "cx": 0.5, "cy": 0.5}),
    ])

    result = replies[1]["result"]
    assert result["match"] is True
    assert result["diff"] == 0.0
    assert "tolerance" in result, "the caller has to be able to see what it was judged against"


def test_the_wait_gate_stays_shut_on_an_unreadable_frame(monkeypatch, capsys, tmp_path):
    ref = _png(tmp_path / "ref.png")
    replies = _serve(monkeypatch, capsys, [
        json.dumps({"id": 1, "cmd": "match-region", "ref": ref,
                    "live": str(tmp_path / "missing.png"), "cx": 0.5, "cy": 0.5}),
    ])

    result = replies[1]["result"]
    assert result["match"] is False
    assert result["diff"] == 1.0
