"""The pointer's heads read the hidden state of every prompt token, so vLLM must
compute them all and expand every board where the model expects it.

Two ways that broke on vLLM 0.25.1, both measured on the gate set (11-01):
a video sent with the bare `<|video_pad|>` was never expanded (vLLM matches the
template's whole vision_start/pad/vision_end triple), and a prompt the prefix
cache had already seen (a marked board with nothing detected is the plain one)
came back with hidden states for its uncached tail only."""
import os
import sys
import types

import numpy as np
import pytest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from captchakraken import clipvideo as CV
from captchakraken.pointer import layout as L

from test_every_captcha_is_asked_the_same_prompt import Template


@pytest.fixture
def service(monkeypatch):
    """A PointerService over a stand-in engine: what it builds and sends, no GPU."""
    service = pytest.importorskip("captchakraken.pointer.service")
    built = {}

    class Processor(Template):
        tokenizer = types.SimpleNamespace(convert_tokens_to_ids=lambda t: 0)

        @classmethod
        def from_pretrained(cls, path):
            return cls()

    class LLM:
        def __init__(self, **kw):
            built.update(kw)

    monkeypatch.setitem(sys.modules, "vllm", types.SimpleNamespace(LLM=LLM))
    monkeypatch.setitem(sys.modules, "transformers", types.SimpleNamespace(AutoProcessor=Processor))
    monkeypatch.setattr(service.vllm_plugin, "register", lambda: None)
    svc = service.PointerService("/models/pointer", detector=None)
    return svc, built


def test_the_prefix_cache_is_off(service):
    _svc, built = service
    assert built["enable_prefix_caching"] is False


def test_a_video_is_sent_where_vllm_expands_it(service):
    svc, _ = service
    h, w = CV.frame_size(704, 704, L.MAX_PIXELS)
    prep = svc.prepare(frames=[np.zeros((h, w, 3), np.uint8)] * 4, marked=False)
    prompt = prep["request"]["prompt"]
    assert prompt.count("<|vision_start|><|video_pad|><|vision_end|>") == 1
    assert prompt.count(L.VIDEO_PAD) == 1
