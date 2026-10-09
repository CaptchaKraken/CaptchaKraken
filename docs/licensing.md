# ⚖️ Licensing

CaptchaKraken is **source-available** under the **CaptchaKraken Source-Available
License v1.1** — see the full text in [`../LICENSE`](../LICENSE). This page is a
plain-English summary, not legal advice.

> **Build *with* it; don't sell *the solve*; don't *ship* the solve inside
> someone else's browser.**

Source-available is **not** the same as open-source: the source is public and you
may build on it, but the license adds the restrictions below. It is not
OSI-approved.

## ✅ Allowed

- **Personal use, research, and education.**
- **Commercial use as an internal, enabling component** of a larger product or
  service that delivers substantial value **beyond** captcha solving itself —
  i.e. where the solve is a means to an end your users are actually paying for.
  Illustrative examples:
  - Web scrapers and data-collection pipelines.
  - Browser automation you build and operate for your own purposes.
  - QA, testing, and accessibility tooling.
- **Running it with any browser, stealth or not.** Camoufox, Puppeteer,
  Playwright, or any anti-detection browser — pointing the solver at your own
  automation is unrestricted, commercially or otherwise.

## ⛔ Not allowed (without a separate commercial agreement)

- **Selling captcha-solving as a service** — any product or API whose primary
  value is solving captchas, powered by this software or its model outputs.
- **Thin wrappers** whose main purpose is solving — browser extensions, hosted
  endpoints, SaaS products, or CLIs that simply expose the solving capability to
  end users.
- **Relaying the model's outputs** (bounding boxes, tile selections, click plans)
  through a paid or public API as a captcha-solving service.
- **Shipping it as a feature of someone else's browser** — you may not bundle,
  preinstall, fetch on demand, or advertise CaptchaKraken as a built-in
  captcha-solving capability of a stealth browser, anti-detection / antidetect
  browser, browser profile or identity manager, or automation platform that you
  distribute or host for third parties. Paid or free makes no difference.

Model outputs are covered to the same extent as the software itself.

### Using vs. shipping

This is the line that trips people up, so plainly:

| You are… | Allowed? |
| --- | --- |
| Scraping with Camoufox + CaptchaKraken for your own business | ✅ Yes |
| Selling a scraping service that happens to solve captchas internally | ✅ Yes |
| Publishing a tutorial or example wiring the two together | ✅ Yes |
| Shipping an antidetect browser with "CaptchaKraken built in" | ⛔ Needs a license |
| Selling a captcha-solving API powered by the model | ⛔ Needs a license |

The restriction is on **distribution**, not use. If you are the one clicking
"run", you are fine.

## Need one of the prohibited uses?

Commercial licensing is available. Open an issue or message the maintainer on
GitHub: [github.com/CaptchaKraken/CaptchaKraken](https://github.com/CaptchaKraken/CaptchaKraken).

## Responsible use

Use responsibly and lawfully — respect the terms of service of any site you
interact with, and applicable anti-fraud and computer-access laws. This project
is for legitimate automation, research, and testing.

---

← Back to [docs index](./README.md)
