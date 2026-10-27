"""The pointer heads: hidden states of one prefill in, decisions out.

Shared by training (the Finetune repo's `src/pointer/model.py`, on transformers
hidden states) and serving (`vllm_plugin`, inside vLLM's pooler), so the two
read the same positions with the same arithmetic.

Option vectors, all from the last hidden layer:
    token    each vision token: where a point can land
    moment   each `<|vision_end|>`: one per frame pair of a video (one for a still)
and one query vector per question, at its `<|quad_end|>`. The element a point
names is not decided here: it is the one under the point (`elements.ids_for`).

A point is a softmax over the chosen moment's tokens plus an offset inside the
winning token, so a coordinate is never decoded digit by digit. A typed answer
reads each `textK` marker through the language model's own head, one token per
marker, in parallel.
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional

import torch
import torch.nn as nn
import torch.nn.functional as F

from . import layout as L


class Positions:
    """Where each kind of state sits in one prompt, from its token ids."""

    def __init__(self, ids: torch.Tensor, token_ids: Dict[str, int]):
        ids = ids.flatten()
        self.q = (ids == token_ids[L.Q_END]).nonzero().flatten()
        vis = (ids == token_ids[L.IMAGE_PAD]) | (ids == token_ids[L.VIDEO_PAD])
        self.vis = vis.nonzero().flatten()
        # A moment ends where its frame pair's tokens do. The chat template wraps a
        # whole video in one more vision_start/end pair, whose end follows another
        # end, not a vision token, and so is not a moment.
        after_vis = torch.zeros_like(vis)
        after_vis[1:] = vis[:-1]
        self.moments = ((ids == token_ids[L.VISION_END]) & after_vis).nonzero().flatten()
        # Earlier screens (`layout.chat`'s history) are images before the board:
        # context the questions see, never a place a point lands. Only the last
        # image is the board.
        self.history = 0
        if (ids == token_ids[L.IMAGE_PAD]).any() and self.moments.numel() > 1:
            if (ids == token_ids[L.VIDEO_PAD]).any():
                raise ValueError("a video board carries no earlier screens")
            self.history = int(self.moments.numel()) - 1
            self.vis = self.vis[self.vis > self.moments[-2]]
            self.moments = self.moments[-1:]
        if self.q.numel() != len(L.QUESTIONS):
            raise ValueError(f"{self.q.numel()} question markers, expected {len(L.QUESTIONS)}")
        n_m = max(int(self.moments.numel()), 1)
        if self.vis.numel() == 0 or self.vis.numel() % n_m:
            raise ValueError(f"{self.vis.numel()} vision tokens do not split into {n_m} moments")
        self.per_moment = self.vis.numel() // n_m
        self.n_moments = n_m


def token_ids(tokenizer) -> Dict[str, int]:
    return {t: tokenizer.convert_tokens_to_ids(t)
            for t in (L.Q_END, L.IMAGE_PAD, L.VIDEO_PAD, L.VISION_END)}


class Heads(nn.Module):
    def __init__(self, d: int, dp: int = 256, text_rank: int = 256):
        super().__init__()
        self.action = nn.Linear(d, len(L.ACTIONS))
        self.count = nn.Linear(d, L.N_COUNTS)
        self.drag_count = nn.Linear(d, L.N_DRAG_COUNTS)
        self.pq = nn.ModuleDict({k: nn.Linear(d, dp) for k in L.KINDS})
        self.pk = nn.Linear(d, dp)
        self.mq, self.mk = nn.Linear(d, dp), nn.Linear(d, dp)
        self.offset = nn.Sequential(nn.Linear(2 * d, 512), nn.GELU(), nn.Linear(512, 2))
        # A low-rank nudge before the language model's head, zero at the start, so
        # a `textK` marker begins as the model's own next-token guess.
        self.text_down = nn.Linear(d, text_rank, bias=False)
        self.text_up = nn.Linear(text_rank, d, bias=False)
        nn.init.zeros_(self.text_up.weight)
        self.scale = 1 / math.sqrt(dp)

    # ── scores (training reads these; `decide` takes their argmax) ───────────
    def point(self, kind: str, hq, htok):                 # [d], [P,d] -> [P]
        return (self.pk(htok) @ self.pq[kind](hq)) * self.scale

    def moment(self, hq, hm):                             # [d], [M,d] -> [M]
        return (self.mk(hm) @ self.mq(hq)) * self.scale

    def off(self, hq, htok):                              # [d], [d] -> [2], in tokens
        return torch.tanh(self.offset(torch.cat([hq, htok], -1))) * 0.5

    def text(self, hq, lm_weight: torch.Tensor):          # [T,d], [V,d] -> [T,V]
        z = hq.float() + self.text_up(self.text_down(hq.float()))
        return z.to(lm_weight.dtype) @ lm_weight.T

    # ── reading one prompt ───────────────────────────────────────────────────
    def views(self, h: torch.Tensor, pos: Positions) -> Dict:
        """h [N,d] (float32) -> the option and query vectors of one prompt."""
        hm = h[pos.moments] if pos.moments.numel() else h[pos.vis].mean(0, keepdim=True)
        return {"q": dict(zip(L.QUESTIONS, h[pos.q])),
                "tok": h[pos.vis].reshape(pos.n_moments, pos.per_moment, -1), "moment": hm}

    @torch.no_grad()
    def decide(self, h: torch.Tensor, pos: Positions, lm_weight: Optional[torch.Tensor]) -> torch.Tensor:
        """h [N,d] -> the packed decision vector (`layout.unpack` reads it).
        `lm_weight` is the language model's output matrix [V,d], for typed text."""
        v = self.views(h.float(), pos)
        q = v["q"]
        parts: List[torch.Tensor] = [
            F.softmax(self.action(q["action"]), -1),
            F.softmax(self.count(q["count"]), -1),
            F.softmax(self.drag_count(q["count"]), -1),
        ]
        pm = F.softmax(self.moment(q["moment"], v["moment"]), -1)
        m = int(pm.argmax())
        tok = v["tok"][m]
        for name, kind in L.SLOTS:
            pp = F.softmax(self.point(kind, q[name], tok), -1)
            t = int(pp.argmax())
            dx, dy = self.off(q[name], tok[t])
            parts.append(torch.stack([torch.tensor(float(t), device=h.device), dx, dy, pp[t]]))
        if lm_weight is not None:
            hq = torch.stack([q[n] for n in L.TEXT])
            ids = self.text(hq, lm_weight).float().argmax(-1).float()
        else:
            ids = torch.full((L.MAX_TEXT,), -1.0, device=h.device)
        parts += [ids, torch.tensor([float(m), float(pm[m])], device=h.device)]
        out = torch.cat([p.float().flatten() for p in parts])
        assert out.numel() == L.PACKED, (out.numel(), L.PACKED)
        return out
