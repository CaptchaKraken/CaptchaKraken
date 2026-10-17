"""One fake DOM for the tests: nodes answer to the exact selector strings they list, so no CSS engine is needed.
The locator half is the Playwright surface the driver duck-types (`locator/filter/all/count/element_handle`)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence


@dataclass
class FakeNode:
    matches: Sequence[str]
    visible: bool = True
    text: str = ""
    value: str = ""
    src: Optional[str] = None
    box: Optional[Dict[str, float]] = None
    throws: bool = False
    frame: Optional[Sequence["FakeNode"]] = None
    children: Sequence["FakeNode"] = field(default_factory=list)


class FakeHandle:
    def __init__(self, node: FakeNode) -> None:
        self.node = node

    def is_visible(self) -> bool:
        return self.node.visible

    def text_content(self) -> str:
        return self.node.text

    def get_attribute(self, name: str) -> Optional[str]:
        return self.node.src if name == "src" else None

    def bounding_box(self) -> Optional[Dict[str, float]]:
        if self.node.throws:
            raise RuntimeError("detached mid-read")
        return self.node.box

    def input_value(self) -> str:
        return self.node.value

    def content_frame(self) -> Optional["FakeScope"]:
        return fake_scope(self.node.frame) if self.node.frame is not None else None

    def screenshot(self, **_: Any) -> None:
        pass

    def scroll_into_view_if_needed(self, **_: Any) -> None:
        pass

    def evaluate(self, *_: Any, **__: Any) -> None:
        return None

    def locator(self, selector: str) -> "FakeLocator":
        return fake_scope(self.node.children).locator(selector)


class FakeLocator:
    """Handles come from `resolve()`; any object with `is_visible()` (and optionally `locator()`) will do."""

    def __init__(self, resolve: Callable[[], List[Any]]) -> None:
        self._resolve = resolve

    def locator(self, selector: str) -> "FakeLocator":
        return FakeLocator(lambda: [h for parent in self._resolve() if hasattr(parent, "locator")
                                    for h in parent.locator(selector)._resolve()])

    def filter(self, visible: Optional[bool] = None) -> "FakeLocator":
        return FakeLocator(lambda: [h for h in self._resolve() if visible is None or h.is_visible() == visible])

    def all(self) -> List["FakeLocator"]:
        return [FakeLocator(lambda h=h: [h]) for h in self._resolve()]

    def count(self) -> int:
        return len(self._resolve())

    def element_handle(self, timeout: Optional[float] = None) -> Optional[Any]:
        found = self._resolve()
        return found[0] if found else None


def _hit(selector: str, matches: Sequence[str]) -> bool:
    return selector in matches or any(part.strip() in matches for part in selector.split(","))


class FakeScope:
    def __init__(self, lookup: Callable[[str], List[Any]]) -> None:
        self._lookup = lookup

    def locator(self, selector: str) -> FakeLocator:
        return FakeLocator(lambda: self._lookup(selector))


def fake_scope(nodes: Optional[Sequence[FakeNode]], unparsable: Sequence[str] = ()) -> FakeScope:
    def lookup(selector: str) -> List[FakeHandle]:
        if selector in unparsable:
            raise ValueError(f"bad selector {selector!r}")
        return [FakeHandle(n) for n in (nodes or ()) if _hit(selector, n.matches)]

    return FakeScope(lookup)


def iframe_matches(src: str, selectors: Sequence[str]) -> List[str]:
    """The iframe selectors an element with this `src` answers to, the way a CSS engine would read them."""
    def wants(sel: str) -> List[str]:
        return re.findall(r'\[src\*="([^"]+)"\]', sel)

    def hit(sel: str) -> bool:
        positive, _, negative = sel.partition(":not(")
        return all(s in src for s in wants(positive)) and not any(s in src for s in wants(negative))

    return [sel for sel in selectors if sel.startswith("iframe[src") and hit(sel)]
