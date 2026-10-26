"""Board in, answer out: the detector, the marks, one vLLM prefill, the decode.

    svc = PointerService("/models/pointer-0.8b", detector="/models/detector_r18.pt")
    svc.solve(image=PIL.Image)                      # a still
    svc.solve(frames=[rgb arrays])                  # a video, `clipvideo`-cut

A still is resized to `layout.board_size`; the detector runs on that, and the
elements it finds are drawn (`marks`) and listed (`layout.prompt_text`). With no
detector, or `marked=False`, the board goes plain and every answer carries points
only. A video always goes plain. The answer is generation 3's shape, plus the
1-based number of each element a point landed on.

Needs the `serve` extra (vLLM, torch, torchvision).
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Sequence, Union

import numpy as np
from PIL import Image

from .. import clipvideo as CV
from . import elements as E
from . import layout as L
from . import marks as M
from . import vllm_plugin


class PointerService:
    def __init__(self, checkpoint: Union[str, Path], detector: Union[str, Path, None] = None,
                 gpu_memory_utilization: float = 0.45, max_model_len: int = 8192, **llm_kwargs):
        vllm_plugin.register()
        from transformers import AutoProcessor
        from vllm import LLM
        self.processor = AutoProcessor.from_pretrained(str(checkpoint))
        tok = self.processor.tokenizer
        self.stop_id = tok.convert_tokens_to_ids("<|im_end|>")
        self.llm = LLM(model=str(checkpoint), runner="pooling", max_model_len=max_model_len,
                       gpu_memory_utilization=gpu_memory_utilization,
                       limit_mm_per_prompt={"image": 1, "video": 1},
                       mm_processor_kwargs={"min_pixels": 64 * 64, "max_pixels": L.MAX_PIXELS}, **llm_kwargs)
        self.detector = None
        if detector is not None:
            from .detector import Detector
            self.detector = Detector(detector)

    # ── one board ────────────────────────────────────────────────────────────
    def prepare(self, image: Optional[Image.Image] = None, frames: Optional[Sequence[np.ndarray]] = None,
                marked: bool = True) -> Dict:
        """The request vLLM gets, and what decoding its answer needs."""
        if (image is None) == (frames is None):
            raise ValueError("give exactly one of image or frames")
        if frames is not None:
            fr = np.stack([np.asarray(f) for f in frames])
            n, h, w = fr.shape[:3]
            if (h, w) != CV.frame_size(h, w, L.MAX_PIXELS):
                raise ValueError(f"frames are {w}x{h}; cut them with clipvideo.clip_video first")
            meta = {"fps": CV.FPS, "frames_indices": list(range(n)), "total_num_frames": n,
                    "duration": n / CV.FPS, "video_backend": "opencv", "do_sample_frames": False}
            return {"request": {"prompt": L.chat(self.processor, [], (w, h), True),
                                "multi_modal_data": {"video": (fr, meta)},
                                "mm_processor_kwargs": {"do_sample_frames": False}},
                    "size": (w, h), "elements": [], "shown": None,
                    "timestamps": CV.pair_timestamps(n)}
        board = image.convert("RGB").resize(L.board_size(*image.size), Image.LANCZOS)
        els = E.number(self.detector.detect(board)) if (marked and self.detector is not None) else []
        shown = M.draw(board, els) if els else board
        return {"request": {"prompt": L.chat(self.processor, els, board.size, False),
                            "multi_modal_data": {"image": shown}},
                "size": board.size, "elements": els, "shown": shown, "timestamps": None}

    def decode(self, prep: Dict, vector: Sequence[float]) -> Dict:
        v = [float(x) for x in vector]
        per_moment, _moments = v[L.PACKED:L.PACKED + vllm_plugin.TRAILER]
        grid = L.token_grid(prep["size"])
        if int(per_moment) != grid[0] * grid[1]:
            raise ValueError(f"vLLM saw {int(per_moment)} tokens per moment, the board has {grid}: "
                             "the processor resized it, so points would be misplaced")
        d = L.unpack(v[:L.PACKED])
        ids = d["text_ids"]
        if self.stop_id in ids:
            ids = ids[:ids.index(self.stop_id)]
        text = self.processor.tokenizer.decode(ids)
        return L.answer(d, grid, text=text, timestamps=prep["timestamps"])

    def solve(self, image: Optional[Image.Image] = None, frames: Optional[Sequence[np.ndarray]] = None,
              marked: bool = True) -> Dict:
        """-> {"answer": generation-3 dict, "elements": numbered elements (board px),
        "shown": the image the model saw (None for a video), "size": board (W, H)}."""
        return self.solve_many([{"image": image, "frames": frames, "marked": marked}])[0]

    def solve_many(self, boards: List[Dict]) -> List[Dict]:
        preps = [self.prepare(b.get("image"), b.get("frames"), b.get("marked", True)) for b in boards]
        outs = self.llm.embed([p["request"] for p in preps], use_tqdm=False)
        return [{"answer": self.decode(p, o.outputs.embedding), "elements": p["elements"],
                 "shown": p["shown"], "size": p["size"]} for p, o in zip(preps, outs)]
