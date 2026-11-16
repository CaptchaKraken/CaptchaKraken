// A typed answer is sent: BotDetect's Validate is pressed after the code is typed.
//
// BotDetect's 280x50 `.BDC_CaptchaDiv` holds only the image; `#captchaCode` and Validate sit beside it in the widget's
// fieldset. The driver found the text box there but looked for Verify only inside the widget, so the code was typed
// and never sent (live 0/9 on captcha.com, 2026-11-13). The markup is the live page's. The Python test of the same
// name drives the same cases.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

import { CaptchaKrakenSolver } from './solver';

function optional(name: string): any | null {
  try {
    return require(name);
  } catch {
    return null;
  }
}

const playwright = optional('playwright');

const BOTDETECT =
  '<form method="post" id="demoForm"><fieldset>' +
  '<div class="BDC_CaptchaDiv" id="demoCaptcha_CaptchaDiv" style="width:280px;height:50px">' +
  '<img class="BDC_CaptchaImage" style="width:250px;height:50px" alt="code"></div>' +
  '<input name="captchaCode" type="text" id="captchaCode">' +
  '<input type="submit" name="validateCaptchaButton" value="Validate" id="validateCaptchaButton">' +
  '</fieldset></form>';

// A login form whose own Submit must never be pressed for a captcha answer: no vendor names it.
const LOGIN =
  '<form id="login"><fieldset>' +
  '<div class="BDC_CaptchaDiv" style="width:280px;height:50px"><img style="width:250px;height:50px"></div>' +
  '<input name="captchaCode" type="text" id="captchaCode">' +
  '<button type="submit" id="signIn">Sign in</button>' +
  '</fieldset></form>';

const CYBERSIARA =
  '<div class="SiaraShield Cyber_Cap challenge-siara-slot"></div>' +
  '<button id="challenge-submit-button" type="button" class="CaptchaSubmit">Verify Me!</button>' +
  '<div id="myModal" class="tooltiptextCyber cs-modal-open" style="display:block">' +
  '<div class="modal-content pluginPopups" style="width:453px;height:286px">' +
  '<div class="mainPageDiv"><div id="page2__cyberscrn" class="cy-sa-page-2"><div id="input-plugin-div">' +
  '<div class="cy-sa-si-main"><div class="imgDiv">' +
  '<img class="cy-sa-si-main-img" id="Img_Original" style="width:322px;height:90px" alt="">' +
  '<a id="a_Refresh" class="ref_icon">&#8635;</a></div></div>' +
  '<div class="ct-input-feild"><input class="Uinput Uinputno-0" id="Input_Captcha" type="text" maxlength="4"></div>' +
  '</div></div></div></div></div>';

test('a typed answer is sent: BotDetect\'s Validate after typing, never a host form\'s Submit, nothing for CyberSiara', { skip: !playwright && 'playwright not installed' }, async (t) => {
  // Any installed Chromium will do: the pinned playwright's own build is often not the one in the cache.
  const cache = path.join(os.homedir(), '.cache', 'ms-playwright');
  const cached = (fs.existsSync(cache) ? fs.readdirSync(cache) : []).filter((d) => d.startsWith('chromium-')).sort().reverse()
    .map((d) => path.join(cache, d, 'chrome-linux64', 'chrome')).filter((exe) => fs.existsSync(exe));
  let browser: any = null;
  const failures: string[] = [];
  for (const executablePath of [undefined, ...cached]) {
    try {
      browser = await playwright.chromium.launch({ headless: true, executablePath, args: ['--no-sandbox', '--disable-dev-shm-usage'] });
      break;
    } catch (err) {
      failures.push(String(err).split('\n')[0]);
    }
  }
  if (!browser) {
    t.skip(`no chromium: ${failures.join('; ')}`);
    return;
  }
  try {
    const verify = async (html: string, typed: boolean): Promise<string | null> => {
      const page = await browser.newPage();
      try {
        await page.setContent(html);
        const solver: any = new CaptchaKrakenSolver();
        const widget = page.locator('.BDC_CaptchaDiv');
        const found = await solver.getVerifyButton(widget, typed ? widget : null);
        return found ? await found.getAttribute('id') : null;
      } finally {
        await page.close();
      }
    };
    assert.equal(await verify(BOTDETECT, true), 'validateCaptchaButton');
    assert.equal(await verify(BOTDETECT, false), null);
    assert.equal(await verify(LOGIN, true), null);

    // SiaraShield's modal as the live page draws it (2026-11-14), images blanked: it checks the answer itself on the
    // fourth letter, and the host's `.CaptchaSubmit` is what opened it, so nothing is pressed.
    const page = await browser.newPage();
    try {
      await page.setContent(CYBERSIARA);
      const solver: any = new CaptchaKrakenSolver();
      const widget = await solver.detectCaptcha(page);
      assert.equal(widget?.vendor, 'cybersiara');
      assert.equal(await widget.at.getAttribute('class'), 'modal-content pluginPopups');
      const box = await solver.answerBox(widget.at, widget.at);
      assert.equal(await box?.getAttribute('id'), 'Input_Captcha');
      assert.equal(await solver.getVerifyButton(widget.at, widget.at), null);
    } finally {
      await page.close();
    }
  } finally {
    await browser.close();
  }
});
