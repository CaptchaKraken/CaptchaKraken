from typing import List, Literal, Optional, Union, Tuple

from pydantic import BaseModel, RootModel

from .kinds import ActionKind


class BoundingBox(RootModel):
    root: Tuple[float, float, float, float]

    def __iter__(self):
        return iter(self.root)

    def __getitem__(self, item):
        return self.root[item]

    def __len__(self):
        return len(self.root)


class Action(BaseModel):
    action: ActionKind
    await_keyframe: Optional[str] = None
    frame: Optional[int] = None
    # Seconds into the clip, on prompt generations that watch an animation as video; `frame` on earlier ones.
    t: Optional[float] = None


class ClickAction(Action):
    action: Literal[ActionKind.CLICK]
    target_bounding_boxes: List[BoundingBox]


class DragAction(Action):
    action: Literal[ActionKind.DRAG]
    # `Optional[...] = None`, never a bare `BoundingBox = None`: pydantic validates a passed value even when it
    # equals the default, and the bare form made every slide (a drag with no source) raise ValidationError.
    source_bounding_box: Optional[BoundingBox] = None
    target_bounding_box: Optional[BoundingBox] = None


class TypeAction(Action):
    action: Literal[ActionKind.TYPE]
    text: str
    target_bounding_box: Optional[BoundingBox] = None


class WaitAction(Action):
    action: Literal[ActionKind.WAIT]
    duration_ms: int


class DoneAction(Action):
    action: Literal[ActionKind.DONE]


class HoldAction(Action):
    """Press on the box and keep pressing until the widget completes (prompt generation 3)."""

    action: Literal[ActionKind.HOLD]
    target_bounding_box: BoundingBox


class RefreshAction(Action):
    """Load a new puzzle instead of solving this one (prompt generation 3). The box is the model's point on the
    control, or None when it saw none; the driver presses the vendor's own control first either way."""

    action: Literal[ActionKind.REFRESH]
    target_bounding_box: Optional[BoundingBox] = None


class SlideAction(Action):
    """Press the handle and move it until the point on the part it moves reaches the target (prompt generation 3).
    The driver tracks that part on screen and steers; nothing about the widget is read from its DOM."""

    action: Literal[ActionKind.SLIDE]
    handle_bounding_box: BoundingBox
    source_bounding_box: BoundingBox
    target_bounding_box: BoundingBox


CaptchaAction = Union[ClickAction, DragAction, TypeAction, WaitAction, DoneAction, HoldAction, RefreshAction,
                      SlideAction]
