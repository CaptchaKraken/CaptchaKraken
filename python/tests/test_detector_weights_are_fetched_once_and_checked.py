"""The element detector's weights are fetched once, checked against the pinned hash,
and refused when they do not match: the client never runs weights it cannot verify.
`auto` runs the lite model on one or two CPUs, and on more only when `standard` would be too slow."""
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
    monkeypatch.setenv("CAPTCHA_KRAKEN_DETECTOR_MODEL", "standard")
    calls = []

    def serve(body, pinned):
        monkeypatch.setitem(detector.WEIGHTS["standard"], "sha256", pinned)
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
    assert detector.WEIGHTS["standard"]["revision"] in calls[0], "the download does not name the pinned revision"


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


@pytest.mark.parametrize("model", sorted(detector.WEIGHTS))
def test_a_released_pin_is_a_commit_and_a_hash(model):
    pin = detector.WEIGHTS[model]
    assert len(pin["revision"]) == 40 and len(pin["sha256"]) == 64


def test_each_model_has_its_own_file_so_one_cannot_be_served_as_the_other():
    assert len({w["file"] for w in detector.WEIGHTS.values()}) == len(detector.WEIGHTS)
    assert len({w["sha256"] for w in detector.WEIGHTS.values()}) == len(detector.WEIGHTS)


@pytest.mark.parametrize("cpus", [0.5, 1, 2])
def test_auto_runs_lite_on_one_or_two_cpus_without_measuring(monkeypatch, cpus):
    monkeypatch.delenv("CAPTCHA_KRAKEN_DETECTOR_MODEL", raising=False)
    monkeypatch.setattr(detector, "usable_cpus", lambda: cpus)
    monkeypatch.setattr(detector, "_time_one_board", lambda det: pytest.fail("measured on a small machine"))
    assert detector.model_name() == "lite"


@pytest.mark.parametrize("lite_s, want", [(0.020, "standard"), (0.036, "standard"), (0.037, "lite"), (0.090, "lite")])
def test_auto_times_lite_and_runs_standard_only_when_it_would_fit(monkeypatch, tmp_path, lite_s, want):
    """standard takes STANDARD_OVER_LITE times lite's time: 0.036 s x 5.5 fits 0.2 s, 0.037 s does not."""
    monkeypatch.delenv("CAPTCHA_KRAKEN_DETECTOR_MODEL", raising=False)
    monkeypatch.setenv("CAPTCHA_KRAKEN_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(detector, "usable_cpus", lambda: 8)
    monkeypatch.setattr(detector, "weights_path", lambda model=None: tmp_path / f"{model}.onnx")
    monkeypatch.setattr(detector, "OnnxDetector", lambda path: path)
    timed = []
    monkeypatch.setattr(detector, "_time_one_board", lambda det: timed.append(det) or lite_s)
    assert detector.model_name() == want
    assert timed == [tmp_path / "lite.onnx"], "auto must time the lite model it already has"
    assert detector.model_name() == want and len(timed) == 1, "the verdict was measured again"


def test_the_config_choice_is_used_and_the_environment_overrides_it(monkeypatch):
    monkeypatch.setattr(detector, "usable_cpus", lambda: 16)
    monkeypatch.delenv("CAPTCHA_KRAKEN_DETECTOR_MODEL", raising=False)
    assert detector.model_name("lite") == "lite" and detector.model_name("Standard") == "standard"
    monkeypatch.setenv("CAPTCHA_KRAKEN_DETECTOR_MODEL", "lite")
    assert detector.model_name("standard") == "lite"
    monkeypatch.setenv("CAPTCHA_KRAKEN_DETECTOR_MODEL", "tiny")
    with pytest.raises(ValueError, match="tiny"):
        detector.model_name()


def test_an_unknown_config_choice_is_refused_when_set():
    with pytest.raises(ValueError, match="detector"):
        detector.configure("heavy")


def test_the_timing_board_is_detected_for_real():
    """The probe runs the network on a drawn board; it must not raise on a real session."""
    class Det:
        def detect(self, im):
            assert im.size == (400, 520)
            return []
    assert detector._time_one_board(Det()) >= 0


def test_a_container_quota_counts_not_the_hosts_cores(monkeypatch, tmp_path):
    """A one-vCPU container sees all of its host's cores; `cpu.max` is what holds it to one."""
    real = detector.Path
    cpu_max = tmp_path / "cpu.max"
    cpu_max.write_text("100000 100000\n")
    monkeypatch.setattr(detector.os, "sched_getaffinity", lambda pid: set(range(16)), raising=False)
    monkeypatch.setattr(detector, "Path", lambda p: cpu_max if p == "/sys/fs/cgroup/cpu.max" else real(p))
    assert detector.usable_cpus() == 1.0
    cpu_max.write_text("max 100000\n")
    assert detector.usable_cpus() == 16.0
