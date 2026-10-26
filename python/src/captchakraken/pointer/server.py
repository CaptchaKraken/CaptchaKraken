"""The /pointer HTTP endpoint: one board per request, generation 3's answer back.

    python -m captchakraken.pointer.server --model /models/pointer-0.8b \\
        --detector /models/detector_r18.pt --port 8001

POST /v1/pointer
    {"image": "<base64 PNG/JPEG>"}                    a still, as captured
    {"frames": ["<base64 JPEG>", ...], "fps": 5.0}    a video, `clipvideo`-cut
    {"marked": false}                                 optional: skip the detector
-> {"answer": {...}, "elements": [{"id", "class", "box", "score"}], "size": [W, H]}

`elements` are in the pixels of the board as the model saw it (`size`), numbered
as the answer's ids are. The client sends no prompt: the server owns it.
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Dict

import numpy as np
from PIL import Image

PATH = "/v1/pointer"


def parse(body: Dict) -> Dict:
    """A request body -> PointerService.solve's arguments. Raises ValueError on a bad one."""
    if ("image" in body) == ("frames" in body):
        raise ValueError("send exactly one of image or frames")
    marked = bool(body.get("marked", True))
    if "image" in body:
        return {"image": Image.open(io.BytesIO(base64.b64decode(body["image"]))).convert("RGB"), "marked": marked}
    from .. import clipvideo as CV
    if abs(float(body.get("fps", CV.FPS)) - CV.FPS) > 1e-6:
        raise ValueError(f"frames must be cut at {CV.FPS} fps by clipvideo, got {body.get('fps')}")
    frames = [np.asarray(Image.open(io.BytesIO(base64.b64decode(f))).convert("RGB")) for f in body["frames"]]
    if len(frames) < 2:
        raise ValueError("a video needs at least two frames")
    return {"frames": frames, "marked": False}


def reply(result: Dict) -> Dict:
    return {"answer": result["answer"], "size": list(result["size"]),
            "elements": [{"id": n, "class": e["class"], "box": [round(v, 1) for v in e["box"]],
                          "score": e["score"]} for n, e in enumerate(result["elements"], 1)]}


def make_handler(service):
    lock = threading.Lock()   # one engine; vLLM batches inside a call, not across threads

    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, obj: Dict) -> None:
            raw = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_POST(self):  # noqa: N802 — http.server's name
            if self.path.rstrip("/") != PATH:
                return self._send(404, {"error": {"message": f"no route {self.path}"}})
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)))
                args = parse(body)
            except (ValueError, KeyError, OSError) as e:
                return self._send(400, {"error": {"message": str(e), "type": "invalid_request"}})
            with lock:
                result = service.solve(**args)
            return self._send(200, reply(result))

        def log_message(self, fmt, *args):  # quiet: one line per request is the caller's to log
            pass

    return Handler


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True, help="an exported pointer checkpoint")
    ap.add_argument("--detector", default=None, help="the element detector; without it every board goes plain")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8001)
    ap.add_argument("--gpu-memory-utilization", type=float, default=0.45)
    a = ap.parse_args()
    from .service import PointerService
    svc = PointerService(a.model, detector=a.detector, gpu_memory_utilization=a.gpu_memory_utilization)
    ThreadingHTTPServer((a.host, a.port), make_handler(svc)).serve_forever()


if __name__ == "__main__":
    main()
