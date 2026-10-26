"""The pointer heads (`pointer/heads.py`): where they read, and what they decide."""
import os
import sys

import pytest

torch = pytest.importorskip("torch")

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from captchakraken.pointer import heads as Hd
from captchakraken.pointer import layout as L

IDS = {L.EL_END: 901, L.Q_END: 902, L.IMAGE_PAD: 903, L.VIDEO_PAD: 904, L.VISION_END: 905}
VSTART, TEXT = 906, 7


def still(n_tokens=12, n_elements=2):
    ids = [TEXT, VSTART] + [IDS[L.IMAGE_PAD]] * n_tokens + [IDS[L.VISION_END], TEXT]
    ids += [TEXT, IDS[L.EL_END]] * n_elements
    ids += [TEXT, IDS[L.Q_END]] * len(L.QUESTIONS)
    return torch.tensor(ids + [TEXT])


def video(moments=3, per=6, outer=True):
    """vLLM drops the template's outer vision pair; transformers keeps it."""
    ids = [TEXT] + ([VSTART] if outer else [])
    for _ in range(moments):
        ids += [TEXT, VSTART] + [IDS[L.VIDEO_PAD]] * per + [IDS[L.VISION_END]]
    ids += ([IDS[L.VISION_END]] if outer else []) + [TEXT]
    ids += [TEXT, IDS[L.Q_END]] * len(L.QUESTIONS)
    return torch.tensor(ids)


def test_a_still_has_one_moment_and_each_element_one_vector():
    pos = Hd.Positions(still(), IDS)
    assert (pos.n_moments, pos.per_moment, pos.el.numel()) == (1, 12, 2)


@pytest.mark.parametrize("outer", [True, False])
def test_a_video_has_a_moment_per_frame_pair_however_it_is_wrapped(outer):
    pos = Hd.Positions(video(outer=outer), IDS)
    assert (pos.n_moments, pos.per_moment) == (3, 6)


def test_a_prompt_missing_its_questions_is_refused():
    with pytest.raises(ValueError):
        Hd.Positions(still()[:-20], IDS)


def test_the_decision_is_the_heads_own_argmax():
    torch.manual_seed(0)
    d = 32
    heads = Hd.Heads(d, dp=16, text_rank=8)
    torch.nn.init.normal_(heads.text_up.weight)
    ids = still(n_tokens=12, n_elements=3)
    pos = Hd.Positions(ids, IDS)
    h = torch.randn(len(ids), d)
    lm = torch.randn(50, d)
    v = heads.decide(h, pos, lm)
    assert v.numel() == L.PACKED
    got = L.unpack(v.tolist())
    q = dict(zip(L.QUESTIONS, h[pos.q]))
    assert got["action_p"].index(max(got["action_p"])) == int(heads.action(q["action"]).argmax())
    tok = h[pos.vis]
    assert got["slots"]["click1"]["token"] == int(heads.point("click", q["click1"], tok).argmax())
    e = int(heads.ident("drop", q["drag1 to"], h[pos.el]).argmax())
    assert got["slots"]["drag1 to"]["element"] == (e if e < 3 else None)
    want = heads.text(torch.stack([q[n] for n in L.TEXT]), lm).argmax(-1).tolist()
    assert got["text_ids"] == want


def test_a_video_point_is_read_on_the_chosen_moment():
    torch.manual_seed(1)
    d = 16
    heads = Hd.Heads(d, dp=8, text_rank=4)
    ids = video(moments=3, per=6)
    pos = Hd.Positions(ids, IDS)
    h = torch.randn(len(ids), d)
    got = L.unpack(heads.decide(h, pos, None).tolist())
    m = got["moment"]
    q = dict(zip(L.QUESTIONS, h[pos.q]))
    on_moment = h[pos.vis].reshape(3, 6, d)[m]
    assert got["slots"]["click1"]["token"] == int(heads.point("click", q["click1"], on_moment).argmax())
    assert 0 <= got["slots"]["click1"]["token"] < 6
