"""The client does not depend on OpenCV: no module imports it, eagerly or inside a function.

The element detector (onnxruntime) finds grids and checkboxes; numpy, scipy, Pillow
and PyAV do the image and video arithmetic. A stray `import cv2` would pass on any
machine that happens to have OpenCV and fail on a clean install of the package.
"""
import ast
import subprocess
import sys
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1] / "src" / "captchakraken"


def _imports_cv2(path: Path) -> list:
    hits = []
    for node in ast.walk(ast.parse(path.read_text(), str(path))):
        names = ([a.name for a in node.names] if isinstance(node, ast.Import)
                 else [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
        hits += [f"{path.relative_to(PACKAGE)}:{node.lineno}" for n in names if n.split(".")[0] == "cv2"]
    return hits


def test_no_module_of_the_package_imports_opencv():
    hits = [h for p in sorted(PACKAGE.rglob("*.py")) if "js" not in p.relative_to(PACKAGE).parts
            for h in _imports_cv2(p)]
    assert not hits, f"OpenCV imported at {hits}"


def test_the_client_imports_with_opencv_unavailable():
    """The solver, the page driver, the CLI and every tool call load where cv2 cannot."""
    code = (
        "import sys; sys.modules['cv2'] = None\n"
        "import captchakraken, captchakraken.solver, captchakraken.page_solver, captchakraken.cli\n"
        "import captchakraken.tool_calls.find_grid, captchakraken.tool_calls.find_checkbox\n"
        "import captchakraken.tool_calls.slide_tracker, captchakraken.tool_calls.fill_tracker\n"
        "import captchakraken.tool_calls.board_painted, captchakraken.keyframes, captchakraken.clipvideo\n"
        "import captchakraken.pointer.detector, captchakraken.pointer.marks, captchakraken.pointer.elements\n"
    )
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                       cwd=PACKAGE.parent)
    assert r.returncode == 0, r.stderr[-2000:]
