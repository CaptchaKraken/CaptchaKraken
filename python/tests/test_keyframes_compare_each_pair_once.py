"""Keyframe extraction measures each pair of frames once.

Its medoid, merge and dedup passes keep re-comparing the same screens: a 100-frame GeeTest
clip asked ~8,000 diffs of ~1,100 distinct pairs. With OpenCV gone each diff costs ~4x more,
so the repeats alone made an animated solve ~2s slower; remembering them made it faster
than it was with OpenCV, with the same keyframes.
"""
import numpy as np

import captchakraken.keyframes as K


def _clip():
    """Two screens that swap every 8 frames, plus a little sensor noise: holds, medoids and merges."""
    rng = np.random.default_rng(0)
    screens = [rng.integers(0, 256, (60, 80, 3), np.uint8) for _ in range(2)]
    frames = []
    for i in range(64):
        f = screens[(i // 8) % 2].astype(np.int16) + rng.integers(-2, 3, (60, 80, 3))
        frames.append(np.clip(f, 0, 255).astype(np.uint8))
    return frames


def test_no_pair_of_frames_is_diffed_twice(monkeypatch):
    real, asked = K.frame_diff_ratio, []

    def counting(a, b):
        asked.append(frozenset((id(a), id(b))))
        return real(a, b)

    monkeypatch.setattr(K, "frame_diff_ratio", counting)
    K.extract_keyframes(_clip())
    assert asked and len(asked) == len(set(asked)), f"{len(asked)} diffs of {len(set(asked))} pairs"


def test_remembering_changes_no_keyframe():
    frames = _clip()
    remembered = K.extract_keyframes(frames)
    measured = K._extract_keyframes(frames, 10.0, None)  # outside extract_keyframes nothing is remembered
    assert [k.source_index for k in remembered.keyframes] == [k.source_index for k in measured.keyframes]
    assert remembered.mode == measured.mode and remembered.frame_states == measured.frame_states
