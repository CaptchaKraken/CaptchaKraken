import pytest
import os
import sys
import time
import shutil
import multiprocessing
from pathlib import Path

try:
    multiprocessing.set_start_method('spawn', force=True)
except RuntimeError:
    pass

sys.path.append(str(Path(__file__).parent.parent))

from captchakraken.solver import CaptchaSolver
from captchakraken.action_types import ClickAction, DragAction, DoneAction
from captchakraken.overlay import add_overlays_to_image

os.environ["CAPTCHA_DEBUG"] = "1"

_SOLVER_INSTANCE = None

def get_solver():
    global _SOLVER_INSTANCE
    if _SOLVER_INSTANCE is None:
        _SOLVER_INSTANCE = CaptchaSolver(
            provider="vllm",
            model="Qwen/Qwen3.5-9B"
        )
    return _SOLVER_INSTANCE

def setup_module(module):
    debug_dir = Path("latestDebugRun")
    if debug_dir.exists():
        try:
            shutil.rmtree(debug_dir)
        except Exception:
            pass
    debug_dir.mkdir(exist_ok=True, parents=True)

def save_final_result_overlay(image_path, actions, test_name):
    if not actions:
        return

    overlays = []
    for i, action in enumerate(actions):
        if isinstance(action, ClickAction):
            for j, bbox in enumerate(action.target_bounding_boxes):
                overlays.append({
                    "bbox": bbox,
                    "number": j + 1,
                    "color": "#FF0000",
                    "box_style": "dashed"
                })
        elif isinstance(action, DragAction):
            if hasattr(action, 'source_bounding_box') and action.source_bounding_box:
                overlays.append({
                    "bbox": action.source_bounding_box,
                    "text": "source",
                    "color": "#0000FF",
                    "box_style": "solid"
                })
            if hasattr(action, 'target_bounding_box') and action.target_bounding_box:
                overlays.append({
                    "bbox": action.target_bounding_box,
                    "text": "target",
                    "color": "#00FF00",
                    "box_style": "solid"
                })

    if overlays:
        output_path = Path("latestDebugRun") / f"final_result_{test_name}.png"

        is_video = any(image_path.lower().endswith(ext) for ext in [".mp4", ".webm", ".gif", ".avi"])
        if is_video:
             image_path = "latestDebugRun/00_base_image.png" 
             if not os.path.exists(image_path):
                 print(f"[Warning] Could not find base image for video result: {image_path}")
                 return

        add_overlays_to_image(image_path, overlays, output_path=str(output_path))
        print(f"[Test] Final result overlay saved to {output_path}")

def run_solver_test(image_path, test_name, expected_action_type=ClickAction, min_actions=0):
    if not os.path.exists(image_path):
        pytest.skip(f"Image not found: {image_path}")

    solver = get_solver()

    print(f"\n[Test] Starting solve for {image_path} ({test_name})")

    start_time = time.time()
    actions = solver.solve(image_path)
    end_time = time.time()

    print(f"[Test] Inference took {end_time - start_time:.2f} seconds")
    print(f"[Test] Actions returned: {actions}")

    if not isinstance(actions, list):
        if isinstance(actions, (ClickAction, DragAction, DoneAction)):
            actions = [actions]
        else:
            actions = []

    total_elements = 0
    for action in actions:
        if isinstance(action, ClickAction):
            total_elements += len(action.target_bounding_boxes)
        else:
            total_elements += 1

    assert total_elements >= min_actions, f"Expected at least {min_actions} elements, got {total_elements}"

    if expected_action_type and actions:
        for action in actions:
            if isinstance(action, DoneAction): continue
            assert isinstance(action, expected_action_type), f"Expected {expected_action_type}, got {type(action)}"

    save_final_result_overlay(image_path, actions, test_name)

    return actions

def test_3x3_recaptcha():
    image_path = "captchaimages/coreRecaptcha/recaptchaImages.png"

    run_solver_test(image_path, "3x3_recaptcha")

def test_4x4_recaptcha():
    image_path = "captchaimages/coreRecaptcha/recaptchaImages2.png"
    run_solver_test(image_path, "4x4_recaptcha")

def test_slanted_grid():
    image_path = "captchaimages/slantedGrid.png"
    run_solver_test(image_path, "slanted_grid")

def test_hcaptcha_puzzle_solve():
    image_path = "captchaimages/hcaptchaPuzzle2.png"
    run_solver_test(image_path, "hcaptcha_puzzle", min_actions=2)

def test_hcaptcha_choose_similar_shapes():
    image_path = "captchaimages/hcaptchaChooseSimilarShapes.png"
    run_solver_test(image_path, "hcaptcha_similar_shapes")

def test_hcaptcha_drag_image_1():
    image_path = "captchaimages/hcaptchaDragImage1.png"
    run_solver_test(image_path, "hcaptcha_drag_1", expected_action_type=DragAction)

def test_hcaptcha_drag_images_3():
    image_path = "captchaimages/hcaptchaDragImages3.png"
    run_solver_test(image_path, "hcaptcha_drag_3", expected_action_type=DragAction)

def test_hcaptcha_video_webm():
    video_path = "captchaimages/hcaptcha_1766539373078.webm"
    run_solver_test(video_path, "hcaptcha_video")

if __name__ == "__main__":
    test_hcaptcha_drag_images_3()
