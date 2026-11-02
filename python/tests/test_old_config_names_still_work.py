"""Configs written against older releases keep working: a renamed option is read under its new name, and the
options that have done nothing since 3.2.0 are still accepted."""

from captchakraken.kinds import Phase
from captchakraken.page_solver import PageSolverConfig


def test_the_old_image_wait_name_sets_the_new_one():
    assert PageSolverConfig(hcaptcha_images_timeout_ms=1234).board_images_timeout_ms == 1234
    assert PageSolverConfig().board_images_timeout_ms == 3_000


def test_options_ignored_since_3_2_are_still_accepted():
    PageSolverConfig(post_solve_delay_ms=1, max_unsupported_resolves=2, max_stale_element_retries=3)


def test_the_old_phase_name_is_the_new_phase():
    assert Phase.HCAPTCHA_IMAGES is Phase.BOARD_IMAGES
