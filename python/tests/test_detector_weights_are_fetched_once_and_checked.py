"""The element detector's weights are fetched once, checked against the pinned hash,
and refused when they do not match: the client never runs weights it cannot verify."""
import hashlib

import pytest

import captchakraken.pointer.detector as detector


class _Response:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def raise_for_status(self):
        pass

    def iter_content(self, size):
        for i in range(0, len(self.body), size):
            yield self.body[i:i + size]


@pytest.fixture
def served(monkeypatch, tmp_path):
    import requests
    monkeypatch.setenv("CAPTCHA_KRAKEN_STATE_DIR", str(tmp_path))
    monkeypatch.delenv("CAPTCHA_KRAKEN_DETECTOR", raising=False)
    calls = []

    def serve(body, pinned):
        monkeypatch.setitem(detector.WEIGHTS, "sha256", pinned)
        monkeypatch.setattr(requests, "get", lambda url, **kw: calls.append(url) or _Response(body))
        return calls
    return serve


def test_the_pinned_file_is_downloaded_once_and_reused(served, tmp_path):
    body = b"onnx bytes" * 1000
    calls = served(body, hashlib.sha256(body).hexdigest())
    first = detector.weights_path()
    assert first.read_bytes() == body and first.parent == tmp_path / "detector"
    assert detector.weights_path() == first
    assert len(calls) == 1, "the weights were downloaded again although they were cached"
    assert detector.WEIGHTS["revision"] in calls[0], "the download does not name the pinned revision"


def test_weights_that_do_not_match_the_pin_are_refused_and_not_kept(served, tmp_path):
    served(b"tampered", hashlib.sha256(b"what was released").hexdigest())
    with pytest.raises(ValueError, match="sha256"):
        detector.weights_path()
    assert not list((tmp_path / "detector").iterdir()), "an unverified download was left on disk"


def test_a_local_file_named_by_the_environment_is_used_as_is(monkeypatch, tmp_path):
    model = tmp_path / "mine.onnx"
    model.write_bytes(b"x")
    monkeypatch.setenv("CAPTCHA_KRAKEN_DETECTOR", str(model))
    assert detector.weights_path() == model


def test_a_released_pin_is_a_commit_and_a_hash():
    assert len(detector.WEIGHTS["revision"]) == 40 and len(detector.WEIGHTS["sha256"]) == 64
