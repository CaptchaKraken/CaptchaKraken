"""The element detector at serve time: a board in, every element on it out, each
with a class, a box, a score and a mask.

torchvision's Mask R-CNN on a ResNet-18 FPN, as trained by the Finetune repo
(`scripts/train_detector.py`, which builds the network with `build` below so the
two cannot disagree). Needs the `serve` extra (torch, torchvision).
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Sequence, Union

import numpy as np

#: h/w: text inputs are ~9:1 wide, which the stock (0.5, 1, 2) cannot propose.
ASPECTS = (0.1, 0.25, 0.5, 1.0, 2.0)
#: Detections this weak are dropped here; `elements.number` applies its own bar.
MIN_SCORE = 0.3


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


class Detector:
    """A checkpoint `scripts/train_detector.py` wrote ({"classes", "min_size",
    "max_size", "state_dict"}); `detect` one image."""

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
        """PIL image or path -> [{"class", "box": [x0, y0, x1, y1] px, "score",
        "mask": ((x, y), bool array)}], best first. The mask is cropped to its
        pixels and placed at (x, y)."""
        from PIL import Image
        from torchvision.transforms.functional import pil_to_tensor
        im = Image.open(image) if isinstance(image, (str, Path)) else image
        x = pil_to_tensor(im.convert("RGB")).float().div(255).to(self.device)
        with self.torch.inference_mode():
            o = self.model([x])[0]
        out = []
        for b, c, s, m in zip(o["boxes"].tolist(), o["labels"].tolist(), o["scores"].tolist(),
                              (o["masks"][:, 0] > 0.5).cpu().numpy()):
            if s < min_score:
                continue
            ys, xs = np.nonzero(m)
            mask = (((int(xs.min()), int(ys.min())), m[ys.min():ys.max() + 1, xs.min():xs.max() + 1])
                    if len(xs) else ((int(b[0]), int(b[1])), np.zeros((0, 0), bool)))
            out.append({"class": self.classes[c - 1], "box": [round(v, 1) for v in b],
                        "score": round(s, 4), "mask": mask})
        return out
