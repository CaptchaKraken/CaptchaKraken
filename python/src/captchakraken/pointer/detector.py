"""The element detector: a board in, every element on it out, each with a class,
a box, a score and a mask.

torchvision's Mask R-CNN on a ResNet-18 FPN. Two runtimes, one network:

  Detector      the torch checkpoint, for serving next to a GPU model (needs the
                `serve` extra: torch, torchvision)
  OnnxDetector  the same weights exported to ONNX, on onnxruntime's CPU kernels.
                This is what the client runs to find a grid or a checkbox before
                any model is asked; `local()` loads the released weights.

Both return the same detections, so code above them never knows which ran.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Union

import numpy as np

#: h/w: text inputs are ~9:1 wide, which the stock (0.5, 1, 2) cannot propose.
ASPECTS = (0.1, 0.25, 0.5, 1.0, 2.0)
#: Detections this weak are dropped here; `elements.number` applies its own bar.
MIN_SCORE = 0.3

#: The released ONNX weights the client runs, pinned by commit and content.
WEIGHTS = {
    "repo": "CaptchaKraken/CaptchaKraken-v2-Detector",
    "revision": "2c47ab53e0158e35299832484889672703058dc7",
    "file": "detector.onnx",
    "sha256": "725f18914ad0f8621ed332752b6fde4949bbbe2b589bbac406f47e07fe2a6a71",
}


def build(num_classes: int, pretrained: bool = False, min_size: Sequence[int] = (512,),
          max_size: int = 1024):
    """`num_classes` excludes background. `pretrained` loads ImageNet ResNet-18
    weights into the backbone only; the heads always start fresh."""
    import torchvision.models as tm
    from torchvision.models.detection import MaskRCNN
    from torchvision.models.detection.anchor_utils import AnchorGenerator
    from torchvision.models.detection.backbone_utils import resnet_fpn_backbone
    backbone = resnet_fpn_backbone(backbone_name="resnet18",
                                   weights=tm.ResNet18_Weights.DEFAULT if pretrained else None,
                                   trainable_layers=5)
    anchors = AnchorGenerator(((32,), (64,), (128,), (256,), (512,)), (ASPECTS,) * 5)
    return MaskRCNN(backbone, num_classes=num_classes + 1, rpn_anchor_generator=anchors,
                    min_size=tuple(min_size), max_size=max_size)


def _rgb(image):
    from PIL import Image
    if isinstance(image, (str, Path)):
        with Image.open(image) as im:
            return im.convert("RGB")
    return image.convert("RGB")


def _detections(boxes, labels, scores, masks, classes: Sequence[str], min_score: float) -> List[Dict]:
    """Raw network output -> [{"class", "box": [x0, y0, x1, y1] px, "score",
    "mask": ((x, y), bool array)}], best first, the mask cropped to its pixels."""
    out = []
    for b, c, s, m in zip(np.asarray(boxes).tolist(), np.asarray(labels).tolist(),
                          np.asarray(scores).tolist(), np.asarray(masks)[:, 0] > 0.5):
        if s < min_score:
            continue
        ys, xs = np.nonzero(m)
        mask = (((int(xs.min()), int(ys.min())), m[ys.min():ys.max() + 1, xs.min():xs.max() + 1])
                if len(xs) else ((int(b[0]), int(b[1])), np.zeros((0, 0), bool)))
        out.append({"class": classes[c - 1], "box": [round(v, 1) for v in b],
                    "score": round(s, 4), "mask": mask})
    return out


class Detector:
    """A checkpoint the Finetune repo's `scripts/train_detector.py` wrote
    ({"classes", "min_size", "max_size", "state_dict"}); `detect` one image."""

    def __init__(self, checkpoint: Union[str, Path], device: Optional[str] = None):
        import torch
        self.torch = torch
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        ck = torch.load(str(checkpoint), map_location=self.device, weights_only=False)
        self.classes = list(ck["classes"])
        self.model = build(len(self.classes), min_size=ck["min_size"], max_size=ck["max_size"])
        self.model.load_state_dict(ck["state_dict"])
        self.model.to(self.device).eval()

    def detect(self, image, min_score: float = MIN_SCORE) -> List[Dict]:
        """PIL image or path -> detections, best first (see `_detections`)."""
        from torchvision.transforms.functional import pil_to_tensor
        x = pil_to_tensor(_rgb(image)).float().div(255).to(self.device)
        with self.torch.inference_mode():
            o = self.model([x])[0]
        return _detections(o["boxes"].cpu(), o["labels"].cpu(), o["scores"].cpu(), o["masks"].cpu(),
                           self.classes, min_score)


class OnnxDetector:
    """An ONNX export of the same network (image (3, H, W) float 0-1 in; boxes,
    labels, scores, masks out; the class names in the model's `classes`
    metadata). CPU only: a board is one image, and the client has no GPU to assume."""

    def __init__(self, model: Union[str, Path]):
        import onnxruntime as ort
        self.session = ort.InferenceSession(str(model), providers=["CPUExecutionProvider"])
        meta = self.session.get_modelmeta().custom_metadata_map
        if "classes" not in meta:
            raise ValueError(f"{model} carries no class names: it was not exported for this client")
        self.classes = json.loads(meta["classes"])

    def detect(self, image, min_score: float = MIN_SCORE) -> List[Dict]:
        """PIL image or path -> detections, best first (see `_detections`)."""
        x = np.ascontiguousarray(np.asarray(_rgb(image), np.float32).transpose(2, 0, 1) / 255.0)
        boxes, labels, scores, masks = self.session.run(None, {"image": x})
        return _detections(boxes, labels, scores, masks, self.classes, min_score)


def weights_path() -> Path:
    """The ONNX file to run: `CAPTCHA_KRAKEN_DETECTOR` when set, else the pinned
    release, downloaded once into the state directory and checked against its hash."""
    # A local .onnx to run instead of the released one (self-hosting, CI, offline).
    local = os.getenv("CAPTCHA_KRAKEN_DETECTOR")
    if local:
        if not Path(local).is_file():
            raise FileNotFoundError(f"CAPTCHA_KRAKEN_DETECTOR={local} is not a file")
        return Path(local)
    from ..config import state_dir
    path = state_dir() / "detector" / f"{WEIGHTS['sha256']}.onnx"
    if path.is_file():
        return path
    import requests
    url = f"https://huggingface.co/{WEIGHTS['repo']}/resolve/{WEIGHTS['revision']}/{WEIGHTS['file']}"
    path.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    with requests.get(url, stream=True, timeout=60) as r:
        r.raise_for_status()
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as tf:
            for chunk in r.iter_content(1 << 20):
                digest.update(chunk)
                tf.write(chunk)
    if digest.hexdigest() != WEIGHTS["sha256"]:
        os.unlink(tf.name)
        raise ValueError(f"{url} does not match the pinned sha256: refusing to run unverified weights")
    os.replace(tf.name, path)
    return path


@lru_cache(maxsize=1)
def local() -> OnnxDetector:
    """The client's detector, loaded once per process."""
    return OnnxDetector(weights_path())


@lru_cache(maxsize=8)
def _detect_file(path: str, mtime_ns: int, size: int) -> List[Dict]:
    return local().detect(path)


def detect_file(path: Union[str, Path]) -> List[Dict]:
    """`local().detect` on an image file, once per version of the file: the grid
    and the checkbox are both asked of the same shot. Treat the result as read-only.
    A file that is missing or is not an image shows no elements: a capture that
    failed is a board with nothing on it to click, not a crash."""
    from PIL import UnidentifiedImageError
    try:
        st = os.stat(path)
        return _detect_file(str(path), st.st_mtime_ns, st.st_size)
    except (FileNotFoundError, UnidentifiedImageError):
        return []
