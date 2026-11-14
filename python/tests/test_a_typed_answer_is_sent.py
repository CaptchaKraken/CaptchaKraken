"""A typed answer is sent: BotDetect's Validate is pressed after the code is typed.

BotDetect's 280x50 `.BDC_CaptchaDiv` holds only the image; `#captchaCode` and the Validate button sit beside it in
the widget's fieldset. The driver found the text box there (`_answer_box`) but looked for Verify only inside the
widget, so the code was typed and never sent: live 0/9 on captcha.com on 2026-11-13, every attempt ending "the model
returned the same answer 3 times running" on the same unchanged image. The markup below is the live page's.
The JS test of the same name drives the same cases.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

sync_playwright = pytest.importorskip("playwright.sync_api", reason="playwright not installed").sync_playwright

from captchakraken.page_solver import PageSolver, PageSolverConfig  # noqa: E402

BOTDETECT = """
<form method="post" id="demoForm"><fieldset>
  <div class="BDC_CaptchaDiv" id="demoCaptcha_CaptchaDiv" style="width:280px;height:50px">
    <img class="BDC_CaptchaImage" id="demoCaptcha_CaptchaImage" style="width:250px;height:50px" alt="code">
  </div>
  <input name="captchaCode" type="text" id="captchaCode">
  <input type="submit" name="validateCaptchaButton" value="Validate" id="validateCaptchaButton">
</fieldset></form>
"""

# A login form whose own Submit must never be pressed for a captcha answer: no vendor names it.
LOGIN = """
<form id="login"><fieldset>
  <div class="BDC_CaptchaDiv" style="width:280px;height:50px"><img style="width:250px;height:50px"></div>
  <input name="captchaCode" type="text" id="captchaCode">
  <button type="submit" id="signIn">Sign in</button>
</fieldset></form>
"""


@pytest.fixture(scope="module")
def browser():
    # Any installed Chromium will do: the pinned playwright's own build is often not the one in the cache.
    cache = Path.home() / ".cache" / "ms-playwright"
    builds = [{}] + [{"executable_path": str(exe)} for exe in sorted(cache.glob("chromium-*/chrome-*/chrome"), reverse=True)]
    with sync_playwright() as p:
        failures = []
        for kwargs in builds:
            try:
                b = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"], **kwargs)
                break
            except Exception as exc:  # noqa: BLE001
                failures.append(str(exc).splitlines()[0])
        else:
            pytest.skip(f"no chromium: {failures}")
        yield b
        b.close()


def _verify(browser, html, typed):
    page = browser.new_page()
    try:
        page.set_content(html)
        solver = PageSolver(PageSolverConfig())
        widget = page.locator(".BDC_CaptchaDiv")
        found = solver._get_verify_button(widget, widget if typed else None)
        return found.get_attribute("id") if found is not None else None
    finally:
        page.close()


def test_validate_beside_the_widget_is_pressed_after_a_typed_answer(browser):
    assert _verify(browser, BOTDETECT, typed=True) == "validateCaptchaButton"


def test_nothing_outside_the_widget_is_pressed_without_a_typed_answer(browser):
    assert _verify(browser, BOTDETECT, typed=False) is None


def test_a_host_forms_own_submit_is_never_taken_for_verify(browser):
    assert _verify(browser, LOGIN, typed=True) is None


# SiaraShield's modal as the live page draws it (cybersiara.com/botattack_testing, 2026-11-14), images blanked: it
# checks the answer itself on the fourth letter, and the host's `.CaptchaSubmit` is what opened it.
CYBERSIARA = """
<div class="SiaraShield Cyber_Cap challenge-siara-slot"></div>
<button id="challenge-submit-button" type="button" class="CaptchaSubmit">Verify Me!</button>
<div id="myModal" class="tooltiptextCyber cs-modal-open" style="display:block">
  <div class="modal-content pluginPopups" style="width:453px;height:286px">
    <div class="mainPageDiv"><div id="page2__cyberscrn" class="cy-sa-page-2"><div id="input-plugin-div">
      <div class="cy-sa-si-main"><div class="imgDiv">
        <img class="cy-sa-si-main-img" id="Img_Original" style="width:322px;height:90px" alt="">
        <a onclick="RefreshCaptcha();" id="a_Refresh" class="ref_icon">&#8635;</a>
      </div></div>
      <div class="ct-input-feild"><input class="Uinput Uinputno-0" id="Input_Captcha" type="text" maxlength="4"></div>
    </div></div></div>
  </div>
</div>
"""


def test_the_cybersiara_modal_is_found_and_typed_into_and_nothing_is_pressed(browser):
    from captchakraken.kinds import Vendor

    page = browser.new_page()
    try:
        page.set_content(CYBERSIARA)
        solver = PageSolver(PageSolverConfig())
        widget = solver.detect_captcha(page)
        assert widget is not None and widget.vendor == Vendor.CYBERSIARA
        assert widget.at.get_attribute("class") == "modal-content pluginPopups"
        box = solver._answer_box(widget.at, widget.at)
        assert box is not None and box.get_attribute("id") == "Input_Captcha"
        assert solver._get_verify_button(widget.at, widget.at) is None
    finally:
        page.close()
