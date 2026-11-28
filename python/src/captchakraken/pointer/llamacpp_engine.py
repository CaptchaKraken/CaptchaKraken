"""The pointer model on llama.cpp: GGUF weights, any GPU with a Vulkan driver, or the CPU.

    svc = LlamaCppPointerService("/models/TwilightV2-2B-GGUF", binary="/opt/pointer_states",
                                 processor="/models/TwilightV2-2B", device="0000:01:00.0")
    svc.solve(image=PIL.Image)

The board is prepared and the answer read exactly as `PointerService` does. The
transformers processor gives the token ids the model was trained on; llama.cpp
(`native/pointer_states` in the repository) runs the language model over that same prompt and
returns the hidden state of every token, and the heads read them on the CPU. Every
request checks llama.cpp's token layout against the processor's, so a prompt that
tokenizes differently fails instead of pointing at the wrong place.

Needs the `serve-llamacpp` extra and the `pointer_states` binary. `processor` is the
folder with the tokenizer and processor files, which the GGUF repositories leave out.
"""
from __future__ import annotations

import json
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Union

import numpy as np

from .. import clipvideo as CV
from . import layout as L
from .service import PointerService

HEADS_FILE = "pointer_heads.safetensors"
MARKER = "<__media__>"
_PIXELS = {"min_pixels": 64 * 64, "max_pixels": L.MAX_PIXELS}
# A video's pixel budget covers all its frames, so the still's cap would shrink every one.
_VIDEO_SIZE = {"shortest_edge": 64 * 64, "longest_edge": L.MAX_PIXELS * CV.MAX_FRAMES}


def _one(folder: Path, pattern: str) -> Path:
    found = sorted(folder.glob(pattern))
    if len(found) != 1:
        raise FileNotFoundError(f"{folder} has {len(found)} files matching {pattern}, expected one")
    return found[0]


def lm_head(gguf_path: Path):
    """The output matrix [vocab, d] as float16. These models tie it to the token embeddings."""
    import gguf
    import torch
    reader = gguf.GGUFReader(str(gguf_path))
    by_name = {t.name: t for t in reader.tensors}
    t = by_name.get("output.weight", by_name["token_embd.weight"])
    w = gguf.quants.dequantize(t.data, t.tensor_type)
    return torch.from_numpy(w.reshape(int(t.shape[1]), int(t.shape[0])).astype(np.float16))


class LlamaCppPointerService(PointerService):
    """`PointerService` with llama.cpp as the engine. Its `__init__` is not called: that builds vLLM.

    `folder` holds one language-model GGUF, its `mmproj-*.gguf` vision encoder, the
    pointer heads and the processor files (or `processor` names their folder); `quant` picks
    the GGUF when there are several. `device` is the PCI address of the GPU to run on;
    without it llama.cpp spreads the model over every GPU it finds."""

    def __init__(self, folder: Union[str, Path], binary: Union[str, Path], quant: str = "Q4_K_M",
                 gpu: bool = True, threads: int = 4, processor: Optional[Union[str, Path]] = None,
                 device: str = ""):
        import torch
        from safetensors.torch import load_file
        from transformers import AutoProcessor

        from . import heads as Hd

        folder = Path(folder)
        self.model_file = _one(folder, f"*-{quant}.gguf")
        mmproj = _one(folder, "mmproj-*.gguf")
        self.processor = AutoProcessor.from_pretrained(str(processor or folder), **_PIXELS)
        tok = self.processor.tokenizer
        self.stop_id = tok.convert_tokens_to_ids("<|im_end|>")
        self.token_ids = Hd.token_ids(tok)
        self._special = {k: tok.convert_tokens_to_ids(k) for k in ("<|vision_start|>", "<|vision_end|>")}
        self.lm_weight = lm_head(self.model_file).float()
        state = {k.removeprefix("pointer_heads."): v for k, v in load_file(str(folder / HEADS_FILE)).items()}
        self.heads = Hd.Heads(self.lm_weight.shape[1]).float()
        self.heads.load_state_dict(state)
        self.heads.eval()
        self._torch, self._hd = torch, Hd
        self._tmp = tempfile.TemporaryDirectory(prefix="pointer-llama-")
        self._lock = threading.Lock()
        self._cmd = [str(binary), str(self.model_file), str(mmproj), "--threads", str(threads)] + (
            ["--cpu"] if not gpu else ["--device", device] if device else [])
        self._start()

    def _start(self) -> None:
        self._proc = subprocess.Popen(self._cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1)
        ready = self._reply()
        if ready.get("n_embd") != self.lm_weight.shape[1] or ready.get("marker") != MARKER:
            raise RuntimeError(f"pointer_states started as {ready}, expected n_embd {self.lm_weight.shape[1]}")

    def _ask(self, req: Dict) -> Dict:
        """One request. A GPU reset (a driver timeout, "device lost") kills the process: start it
        again and retry once, so one bad moment on the card is one slow board, not a dead server."""
        for attempt in (0, 1):
            if self._proc.poll() is not None:
                self._start()
            try:
                self._proc.stdin.write(json.dumps(req) + "\n")
                self._proc.stdin.flush()
                reply = self._reply()
            except (BrokenPipeError, RuntimeError):
                if attempt:
                    raise
                continue
            if reply["ok"]:
                return reply
            try:
                self._proc.wait(timeout=5)  # an error it survives leaves it running
            except subprocess.TimeoutExpired:
                raise RuntimeError(f"pointer_states: {reply['error']}") from None
            if attempt:
                raise RuntimeError(f"pointer_states: {reply['error']}")
        raise AssertionError("unreachable")

    def _reply(self) -> Dict:
        line = self._proc.stdout.readline()
        if not line:
            raise RuntimeError(f"pointer_states exited with {self._proc.wait()}; its log is on stderr")
        return json.loads(line)

    def close(self) -> None:
        self._proc.stdin.close()
        self._proc.wait()
        self._tmp.cleanup()

    def _inputs(self, request: Dict):
        """The processor's ids for the prompt `prepare` built, and the pixels behind each vision span."""
        mm = request["multi_modal_data"]
        if "video" in mm:
            frames, _meta = mm["video"]
            n = len(frames)
            x = self.processor(text=[L.chat(self.processor, True)], videos=[list(frames)],
                               video_metadata=[{"fps": CV.FPS, "frames_indices": list(range(n)), "total_num_frames": n}],
                               do_sample_frames=False, cap_pixels_per_frame=False, videos_kwargs={"size": _VIDEO_SIZE},
                               return_tensors="np")
            # Qwen pairs frames into one temporal patch and repeats the last of an odd count.
            frames = [np.asarray(f) for f in frames] + ([np.asarray(frames[-1])] if n % 2 else [])
            return x["input_ids"][0].tolist(), [(f, True) for f in frames]
        images = mm["image"] if isinstance(mm["image"], list) else [mm["image"]]
        x = self.processor(text=[L.chat(self.processor, False, history=len(images) - 1)], images=images,
                           return_tensors="np")
        return x["input_ids"][0].tolist(), [(np.asarray(i.convert("RGB")), False) for i in images]

    def _prompt(self, ids: Sequence[int], n_media: int) -> str:
        """`ids` as text, each vision span a media marker: llama.cpp writes the span's tokens itself.
        A video's span is a frame pair, two frames that llama.cpp merges back into one."""
        pads = {self.token_ids[L.IMAGE_PAD]: 1, self.token_ids[L.VIDEO_PAD]: 2}
        start, end = self._special["<|vision_start|>"], self._special["<|vision_end|>"]
        parts, text, i = [], [], 0
        while i < len(ids):
            if ids[i] == start and i + 1 < len(ids) and ids[i + 1] in pads:
                j = ids.index(end, i)
                parts += [self.processor.tokenizer.decode(text, skip_special_tokens=False)] if text else []
                parts.append(MARKER * pads[ids[i + 1]])
                text, i = [], j + 1
            else:
                text.append(ids[i])
                i += 1
        parts += [self.processor.tokenizer.decode(text, skip_special_tokens=False)] if text else []
        prompt = "".join(parts)
        if prompt.count(MARKER) != n_media:
            raise ValueError(f"the prompt has {prompt.count(MARKER)} vision slots for {n_media} pictures")
        return prompt

    def states(self, request: Dict):
        """(token ids, final hidden states [n_tokens, d]) for one prepared request."""
        ids, media = self._inputs(request)
        files = []
        for k, (px, video) in enumerate(media):
            f = Path(self._tmp.name) / f"{k}.rgb"
            f.write_bytes(np.ascontiguousarray(px, dtype=np.uint8).tobytes())
            files.append({"rgb": str(f), "w": int(px.shape[1]), "h": int(px.shape[0]), "video": video})
        out = Path(self._tmp.name) / "states.f32"
        req = {"prompt": self._prompt(ids, len(media)), "media": files, "out": str(out)}
        with self._lock:
            reply = self._ask(req)
            h = np.fromfile(out, dtype=np.float32).reshape(-1, reply["n_embd"])
        pad = self.token_ids[L.VIDEO_PAD if media and media[0][1] else L.IMAGE_PAD]
        seen = [t for c in reply["chunks"] for t in (c["text"] if "text" in c else [pad] * c["media"])]
        if seen != ids:
            raise RuntimeError("llama.cpp tokenized the prompt differently from the model's processor "
                               f"({len(seen)} tokens against {len(ids)}); the heads would read the wrong states")
        return ids, h

    def vector(self, request: Dict) -> List[float]:
        """The packed decision vector and the two trailing counts, as vLLM's pooler returns them."""
        ids, h = self.states(request)
        torch = self._torch
        with torch.inference_mode():
            pos = self._hd.Positions(torch.tensor(ids), self.token_ids)
            v = self.heads.decide(torch.from_numpy(h), pos, self.lm_weight)
        return [float(t) for t in v] + [float(pos.per_moment), float(pos.n_moments)]

    def solve_many(self, boards: List[Dict], top: int = 3) -> List[Dict]:
        results = []
        for b in boards:
            p = self.prepare(b.get("image"), b.get("frames"), b.get("history", ()))
            answers = self.decode_answers(p, self.vector(p["request"]), b.get("avoid", ()), top)
            results.append({"answer": answers[0], "answers": answers, "shown": p["shown"], "size": p["size"]})
        return results
