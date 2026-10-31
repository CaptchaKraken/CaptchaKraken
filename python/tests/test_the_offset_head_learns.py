"""The point offset head must learn at a pointer trainer's settings.

The base model's hidden states are large. Fed raw through a final tanh, one
AdamW step at a head learning rate of 1e-3 saturated the head for good, and
every point stayed at its token's centre. Here the same optimiser drives the
head on inputs of that scale, and it must beat a constant zero."""
import os
import sys

import pytest

torch = pytest.importorskip("torch")
import torch.nn.functional as F  # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from captchakraken.pointer import heads as Hd  # noqa: E402


def test_the_offset_head_learns_from_large_hidden_states_at_the_head_lr():
    torch.manual_seed(0)
    d = 64
    H = Hd.Heads(d)
    # Hidden states at the base model's scale; the gold offset is a fixed linear
    # read of them, so a head that is not saturated can learn it.
    hq, ht = torch.randn(256, d) * 20, torch.randn(256, d) * 20
    gold = torch.tanh(torch.cat([hq, ht], -1) @ torch.randn(2 * d, 2) / 200) * 0.5
    opt = torch.optim.AdamW(H.offset.parameters(), lr=1e-3, weight_decay=0.0)
    for step in range(300):
        i = torch.randint(0, 256, (8,))
        loss = F.smooth_l1_loss(torch.stack([H.off(a, b) for a, b in zip(hq[i], ht[i])]), gold[i], beta=0.05)
        opt.zero_grad()
        loss.backward()
        torch.nn.utils.clip_grad_norm_(H.offset.parameters(), 1.0)
        opt.step()
    with torch.no_grad():
        got = torch.stack([H.off(a, b) for a, b in zip(hq, ht)]).clamp(-0.5, 0.5)
    zero = F.smooth_l1_loss(torch.zeros_like(gold), gold, beta=0.05)
    assert F.smooth_l1_loss(got, gold, beta=0.05) < 0.5 * zero
