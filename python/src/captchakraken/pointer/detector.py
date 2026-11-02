"""The element detector: a board in, every element on it out, each with a class,
a box, a score and a mask.

torchvision's Mask R-CNN, in two sizes (`WEIGHTS`): `standard`, a ResNet-18 FPN,
and `lite`, a MobileNetV3-Large FPN ~6x faster on one CPU. Two runtimes, one network:

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
from functools import lru_cache, partial
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Union

import numpy as np

#: h/w: text inputs are ~9:1 wide, which the stock (0.5, 1, 2) cannot propose.
ASPECTS = (0.1, 0.25, 0.5, 1.0, 2.0)
#: Detections this weak are dropped here; `elements.number` applies its own bar.
MIN_SCORE = 0.3

#: The released ONNX weights, pinned by commit and content: `standard` (ResNet-18
#: FPN) and `lite` (MobileNetV3-Large FPN, ~6x faster on one CPU).
WEIGHTS = {
    "standard": {
        "repo": "CaptchaKraken/CaptchaKraken-v2-Detector",
        "revision": "2c47ab53e0158e35299832484889672703058dc7",
        "file": "detector.onnx",
        "sha256": "725f18914ad0f8621ed332752b6fde4949bbbe2b589bbac406f47e07fe2a6a71",
    },
    "lite": {
        "repo": "CaptchaKraken/CaptchaKraken-v2-Detector",
        "revision": "184987101f0b2ad3f2d5e1dfc4697108c4f2d967",
        "file": "detector-lite.onnx",
        "sha256": "b654e6b02028e29ccdc4c4ca0f52ba7110c9f064f97d507f03ac308745eb41ad",
    },
}
#: What `auto` may choose from, and the names a checkpoint's `arch` has had.
MODELS = ("auto", *WEIGHTS)
_ARCH_NAMES = {"standard": "standard", "lite": "lite", "normal": "standard", "light": "lite"}
#: `auto` runs `lite` at or below this many usable CPUs without measuring anything.
LITE_AT_CPUS = 2
#: Above that, `auto` times `lite` once and runs `standard` only when it is predicted
#: to finish a board inside this budget. `standard` takes this many times as long as
#: `lite` on the same CPUs. Measured on 520x570 grid boards, one x86 core per thread:
#: 5.3x at 1 thread, 5.1x at 2, 4.6x at 4, 3.9x at 8. The ratio falls as threads are
#: added, so the worst of them, rounded up, never predicts `standard` too fast.
AUTO_BUDGET_S = 0.2
STANDARD_OVER_LITE = 5.5


def build(num_classes: int, pretrained: bool = False, min_size: Sequence[int] = (512,),
          max_size: int = 1024, arch: str = "standard"):
    """`num_classes` excludes background. `pretrained` loads ImageNet weights into
    the backbone only; the heads always start fresh. `arch` is the checkpoint's
    (one without it is `standard`); the Finetune repo's `src/detector.py` builds the same."""
    import torchvision.models as tm
    from torchvision.models.detection import MaskRCNN
    from torchvision.models.detection.anchor_utils import AnchorGenerator
    anchors = AnchorGenerator(((32,), (64,), (128,), (256,), (512,)), (ASPECTS,) * 5)
    if arch not in _ARCH_NAMES:
        raise ValueError(f"unknown detector arch {arch!r}: one of {tuple(WEIGHTS)}")
    arch = _ARCH_NAMES[arch]
    if arch == "standard":
        from torchvision.models.detection.backbone_utils import resnet_fpn_backbone
        backbone = resnet_fpn_backbone(backbone_name="resnet18",
                                       weights=tm.ResNet18_Weights.DEFAULT if pretrained else None,
                                       trainable_layers=5)
        return MaskRCNN(backbone, num_classes=num_classes + 1, rpn_anchor_generator=anchors,
                        min_size=tuple(min_size), max_size=max_size)
    import torch.nn as nn
    from torchvision.models.detection.backbone_utils import BackboneWithFPN
    from torchvision.models.detection.faster_rcnn import FastRCNNPredictor, TwoMLPHead
    from torchvision.models.detection.mask_rcnn import MaskRCNNHeads, MaskRCNNPredictor
    from torchvision.ops.feature_pyramid_network import LastLevelMaxPool
    from torchvision.ops.misc import FrozenBatchNorm2d
    features = tm.mobilenet_v3_large(
        weights=tm.MobileNet_V3_Large_Weights.DEFAULT if pretrained else None,
        norm_layer=FrozenBatchNorm2d if pretrained else nn.BatchNorm2d).features
    # The last block at each of strides 4, 8, 16 and 32: small items need stride 4.
    taps, channels = {"3": "0", "6": "1", "12": "2", "16": "3"}, [24, 40, 112, 960]
    # A 1024-wide box head like `standard`'s: at 256 the GeeTest bar (a box filling the whole shot)
    # scored 0.25-0.70 as a checkbox where `standard` scores 0.999, for 12 ms less on one CPU.
    ch, rep = 128, 1024
    # GroupNorm: MobileNetV3's stride-4 and stride-8 outputs are unnormalised, 11x and 5x ResNet's scale.
    backbone = BackboneWithFPN(features, taps, channels, ch, extra_blocks=LastLevelMaxPool(),
                               norm_layer=partial(nn.GroupNorm, 32))
    return MaskRCNN(backbone, num_classes=None, rpn_anchor_generator=anchors,
                    min_size=tuple(min_size), max_size=max_size,
                    box_head=TwoMLPHead(ch * 7 * 7, rep), box_predictor=FastRCNNPredictor(rep, num_classes + 1),
                    mask_head=MaskRCNNHeads(ch, [ch, ch], 1),
                    mask_predictor=MaskRCNNPredictor(ch, ch, num_classes + 1),
                    # 1000 before NMS: GeeTest's five-in-a-row balls sit on the stride-4 level, the most
                    # crowded, and at 300 two in three were never proposed. 300 after keeps it at ~100 ms.
                    rpn_pre_nms_top_n_test=1000, rpn_post_nms_top_n_test=300, box_detections_per_img=64)


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
        self.model = build(len(self.classes), min_size=ck["min_size"], max_size=ck["max_size"],
                           arch=ck.get("arch", "standard"))
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
        so = ort.SessionOptions()
        # One thread per CPU the process may use, not per core it can see: a container held to
        # one vCPU would otherwise run a thread for every host core on it.
        cpus = usable_cpus()
        if cpus < (os.cpu_count() or 1):
            so.intra_op_num_threads = max(1, int(cpus))
        self.session = ort.InferenceSession(str(model), so, providers=["CPUExecutionProvider"])
        meta = self.session.get_modelmeta().custom_metadata_map
        if "classes" not in meta:
            raise ValueError(f"{model} carries no class names: it was not exported for this client")
        self.classes = json.loads(meta["classes"])

    def detect(self, image, min_score: float = MIN_SCORE) -> List[Dict]:
        """PIL image or path -> detections, best first (see `_detections`)."""
        x = np.ascontiguousarray(np.asarray(_rgb(image), np.float32).transpose(2, 0, 1) / 255.0)
        boxes, labels, scores, masks = self.session.run(None, {"image": x})
        return _detections(boxes, labels, scores, masks, self.classes, min_score)


def usable_cpus() -> float:
    """The CPUs this process may run on: its affinity, capped by a cgroup quota. A
    one-vCPU container usually sees every core of its host and is held to one by
    `cpu.max`, so the core count alone would pick the heavy model there."""
    try:
        n = float(len(os.sched_getaffinity(0)))
    except (AttributeError, OSError):
        n = float(os.cpu_count() or 1)
    try:
        quota, period = Path("/sys/fs/cgroup/cpu.max").read_text().split()[:2]
        if quota != "max":
            n = min(n, int(quota) / int(period))
    except (OSError, ValueError):
        pass
    return n


def model_name(choice: Optional[str] = None) -> str:
    """The released model to run. `choice` is the config's `detector` (`auto`,
    `standard` or `lite`); `CAPTCHA_KRAKEN_DETECTOR_MODEL` overrides it."""
    name = (os.getenv("CAPTCHA_KRAKEN_DETECTOR_MODEL") or choice or "auto").strip().lower()
    if name not in MODELS:
        raise ValueError(f"detector model {name!r}: one of {', '.join(MODELS)}")
    return _auto() if name == "auto" else name


def _auto() -> str:
    """`lite` on LITE_AT_CPUS usable CPUs or fewer. Otherwise `lite` is timed on a board
    once, and `standard` runs when STANDARD_OVER_LITE times that fits AUTO_BUDGET_S. The
    verdict is kept beside the weights, keyed on what it measured, so it runs once a machine."""
    cpus = usable_cpus()
    if cpus <= LITE_AT_CPUS:
        return "lite"
    import platform
    from ..config import state_dir
    key = f"{platform.machine()}|{platform.processor()}|{os.cpu_count()}|{cpus:g}|{WEIGHTS['lite']['sha256'][:16]}"
    cache = state_dir() / "detector" / "auto.json"
    try:
        seen = json.loads(cache.read_text())
        if seen.get("key") == key and seen.get("model") in WEIGHTS:
            return seen["model"]
    except (OSError, ValueError):
        pass
    seconds = _time_one_board(OnnxDetector(weights_path("lite")))
    model = "standard" if seconds * STANDARD_OVER_LITE <= AUTO_BUDGET_S else "lite"
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({"key": key, "model": model, "lite_s": round(seconds, 4)}))
    except OSError:
        pass
    return model


def _time_one_board(det: "OnnxDetector") -> float:
    """The best of three detections on a drawn 3x3 board (one warm-up first)."""
    import time
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (400, 520), (255, 255, 255))
    d = ImageDraw.Draw(im)
    d.rectangle((0, 0, 399, 96), fill=(74, 144, 226))
    for r in range(3):
        for c in range(3):
            x, y = 6 + c * 130, 110 + r * 130
            d.rectangle((x, y, x + 124, y + 124), fill=(40 + 60 * r, 90 + 50 * c, 160 - 40 * r))
    det.detect(im)
    best = float("inf")
    for _ in range(3):
        t = time.perf_counter()
        det.detect(im)
        best = min(best, time.perf_counter() - t)
    return best


def weights_path(model: Optional[str] = None) -> Path:
    """The ONNX file to run: `CAPTCHA_KRAKEN_DETECTOR` when set, else the pinned
    release of `model` (`standard` or `lite`; default `model_name()`), downloaded
    once into the state directory and checked against its hash."""
    # A local .onnx to run instead of the released one (self-hosting, CI, offline).
    local = os.getenv("CAPTCHA_KRAKEN_DETECTOR")
    if local:
        if not Path(local).is_file():
            raise FileNotFoundError(f"CAPTCHA_KRAKEN_DETECTOR={local} is not a file")
        return Path(local)
    pin = WEIGHTS[model or model_name()]
    from ..config import state_dir
    path = state_dir() / "detector" / f"{pin['sha256']}.onnx"
    if path.is_file():
        return path
    import requests
    url = f"https://huggingface.co/{pin['repo']}/resolve/{pin['revision']}/{pin['file']}"
    path.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    with requests.get(url, stream=True, timeout=60) as r:
        r.raise_for_status()
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as tf:
            for chunk in r.iter_content(1 << 20):
                digest.update(chunk)
                tf.write(chunk)
    if digest.hexdigest() != pin["sha256"]:
        os.unlink(tf.name)
        raise ValueError(f"{url} does not match the pinned sha256: refusing to run unverified weights")
    os.replace(tf.name, path)
    return path


_CHOICE: Optional[str] = None


def configure(choice: Optional[str]) -> None:
    """Set the config's `detector` choice (`auto`, `standard`, `lite`) for this process; the next
    detection loads it. A process that never calls this runs the shipped config file's choice."""
    global _CHOICE
    if choice is not None and choice.strip().lower() not in MODELS:
        raise ValueError(f"detector {choice!r}: one of {', '.join(MODELS)}")
    if choice != _CHOICE:
        _CHOICE = choice
        local.cache_clear()
        _detect_file.cache_clear()


@lru_cache(maxsize=1)
def local() -> OnnxDetector:
    """The client's detector, loaded once per process."""
    if os.getenv("CAPTCHA_KRAKEN_DETECTOR"):
        return OnnxDetector(weights_path())
    if _CHOICE is None:
        # Nothing configured this process (the CLI, a script): the shipped config file's choice.
        from ..selectors import DEFAULT_CONFIG
        return OnnxDetector(weights_path(model_name(DEFAULT_CONFIG.detector)))
    return OnnxDetector(weights_path(model_name(_CHOICE)))


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
