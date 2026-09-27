# Benchmarks

Two measurements, because they answer two different questions, and a single
percentage that blurs them is worth nothing to anyone deciding whether to buy.

- **[On real captchas](#on-real-captchas)** — the client driving a real browser
  against the vendors' own public demo pages, end to end, until the vendor
  accepts. This is the number you experience.
- **[On static images](#on-static-images)** — the model alone, answering a
  held-out set of real captured puzzles. This is the number that says which
  *kinds* of puzzle it is good at.

The browser number is always the lower of the two, and always the more honest
one: a correct answer still has to be clicked, in the right place, before the
widget's own timeout, past whatever the vendor thinks of the mouse that moved.

Every figure here is a count over a dated run against a named model. Nothing is
extrapolated and nothing is rounded up.

---

## On real captchas

Each row is one puzzle type driven on the **vendor's own public demo page**
through the hosted API, with every attempt scored. Counts, not percentages: at
these sample sizes a percentage implies a precision the count does not have.

**A row is the whole widget, not one puzzle.** Vendors ask again — reCAPTCHA
keeps going until it is satisfied, and a later round is often a different shape
from the one that opened. A row is named for the puzzle the vendor *opened*
with, and the time covers every round after it. That is both the honest reading and the stronger claim.

The median is challenge-visible to verified: the span from the puzzle appearing
to the vendor accepting. Page load, the checkbox and the widget's own boot are
the site's latency, not ours, and are excluded.

Both models, driven the same way on the same pages, so the two columns can be
subtracted. Neither column is filled in from the static table below: a browser
figure projected from a static one is a projection wearing a measurement's
clothes, and the whole reason this table exists is that the two disagree.

The vendors do not deal the same puzzle to both runs on demand, so where one
model drove a puzzle the other never met, the row prints with an em dash rather
than being dropped. An incomplete measurement stays visibly incomplete.

<!-- BEGIN GENERATED: real-captcha table -->

Measured **2026-09-15** through the hosted API, every attempt scored.

| Vendor | Puzzle | Twilight solved | Twilight median | Abyss solved | Abyss median |
|---|---|---:|---:|---:|---:|
| GeeTest | 3×3 photo grid | 6/6 | 6.6s | 6/6 | 6.9s |
| GeeTest | Cycling line art | 6/6 | 23.6s | 5/6 | 18.0s |
| GeeTest | Gobang | 6/6 | 6.7s | 6/6 | 6.4s |
| GeeTest | Icon crush | 3/6 | 12.7s | 4/6 | 6.1s |
| GeeTest | Ordered icon click | 5/6 | 9.8s | 6/6 | 13.2s |
| GeeTest | Slide jigsaw | 6/6 | 7.1s | 6/6 | 6.4s |
| reCAPTCHA | 3×3 dynamic | 4/8 | 29.8s | 8/8 | 19.2s |
| reCAPTCHA | 3×3 tile grid | 9/10 | 10.6s | 12/12 | 9.7s |
| reCAPTCHA | 4×4 tile grid | 10/10 | 12.6s | 9/9 | 9.5s |

**Twilight: 55/64 scored attempts solved**, over 9 puzzle types.

**Abyss: 62/65 scored attempts solved**, over 9 puzzle types.

The vendors behind these rows deal one puzzle per target, so every row is the same puzzle in both runs and the two totals can be subtracted.

<!-- END GENERATED: real-captcha table -->

---

## On static images

Both models answering the same real captured puzzles they have never trained
on, one screenshot at a time, with no browser involved. Scored the way a widget
scores: **exact set match**, pass or fail per puzzle, with the vendor's own
leeway. No partial credit — a partially-correct grid answer is a rejected
captcha.

Every real capture is held out; nothing hand-labelled is trained on. These
measure skill rather than memorisation.

The two columns are one run. The gate scores the model under test and carries
the pinned baseline's figure for the same capture beside it, so these are the
same puzzles, the same held-out split and the same solver — which is what makes
subtracting one column from the other mean anything.

The `n` column is how many held-out captures of that puzzle we hold. Where it is
small the rate is one or two puzzles wide: a row at n=2 moving 50 points is one
puzzle changing its mind, not a trend. Read those loosely, and prefer the rows
with three figures behind them.

<!-- BEGIN GENERATED: static-image table -->

Measured **2026-09-11** on **678 held-out captures** across **18 puzzle types**, including the ones both models are weakest on.

| Vendor | Puzzle | n | Twilight | Abyss | Twilight, est. widget | Abyss, est. widget |
|---|---|---:|---:|---:|---:|---:|
| BotDetect | Distorted text | 28 | 93% | 96% | — | — |
| GeeTest v3 | Slide jigsaw (v3) | 11 | 73% | 73% | — | — |
| GeeTest v4 | 3x3 photo grid | 12 | 83% | 83% | — | — |
| GeeTest v4 | Cycling line art | 74 | 97% | 99% | — | — |
| GeeTest v4 | Five-in-a-row board | 26 | 88% | 100% | — | — |
| GeeTest v4 | Match-three swap | 24 | 83% | 92% | — | — |
| GeeTest v4 | Ordered icon click | 25 | 76% | 80% | — | — |
| GeeTest v4 | Slide jigsaw | 23 | 96% | 87% | — | — |
| Lemin | Cropped piece | 11 | 100% | 100% | — | — |
| MTCaptcha | Distorted text | 29 | 97% | 97% | — | — |
| NetEase Yidun | Icon click | 12 | 75% | 92% | — | — |
| NetEase Yidun | Picture click | 14 | 71% | 71% | — | — |
| NetEase Yidun | Slide jigsaw | 12 | 92% | 100% | — | — |
| Prosopo | 3x3 image grid | 11 | 73% | 73% | 92% * | 92% * |
| Tencent | Slide | 12 | 92% | 92% | — | — |
| Yandex | Distorted text | 23 | 61% | 65% | — | — |
| reCAPTCHA | 3x3 tile grid | 281 | 68% | 67% | — | — |
| reCAPTCHA | 4x4 tile grid | 50 | 44% | 42% | — | — |

**One board, one answer: 76% → 77%** (+1 point absolute), weighted by how many captures of each puzzle we hold.

**Estimated chance of clearing the whole widget: 92% → 92%**, over the one type here we cannot summon on demand. An ESTIMATE on both sides — nothing in this column was driven. What we drove is the real-captcha table above.

The two widget columns are **estimates, not measurements**, and every cell in them carries the mark for that reason. A puzzle type that cannot be summoned on demand cannot be driven a fixed number of times, so the estimate applies that vendor's **measured** leniency and **measured** board allowance to this type's one-shot rate. A blank is a type whose vendor allowance we have not measured — unmeasured, not zero. Types we DID drive are deliberately absent here and present in the real-captcha table above, with the counts behind them: a browser rate and a projection are different quantities, and one column cannot hold both.

These estimate the **whole widget**, the same unit the real-captcha table uses — not one board. That is why a figure here can sit BELOW the one-shot beside it: where a vendor asks for two boards in a row, both have to land, so a type at 12% a board clears the widget less often than 12% of the time, however many retries it is given. Where a vendor deals one board, the retries can only push it up.

Abyss is ahead by ten points or more on **2** of the 18 types and behind by five or more on **1**. Both counts are here because a table that only showed the wins would not be a measurement.

<!-- END GENERATED: static-image table -->

---

## Which model the hosted API serves

The current client asks for **Abyss** by name and is served it. A client old
enough not to name it, and any request that names no model at all, is served
**Twilight**. Abyss is not downloadable — its weights are hosted only, and that
is not a release schedule. Twilight's are public and free to self-host. See
[licensing.md](./licensing.md).

---

## Why the two tables disagree

A puzzle can score well on static images and badly in a browser, and the reasons
are worth naming because a self-hoster will hit them too.

- **An animated puzzle has to be recorded before it can be read.** A still
  screenshot of a cycling board is a picture of one frame, and the answer may
  belong to a frame that has already gone. Those rows carry the longest medians.
- **A drag has to land.** Two boxes correct out of two is a solve; one out of
  two is a rejection. The static score gives partial geometry credit that the
  widget never gives.
- **The vendor gets a vote.** A correct answer clicked by a mouse the vendor
  dislikes is still a failed captcha.

Grids are sent with the cell numbers drawn on, and this is not cosmetic: on raw
un-numbered screenshots the same model scores **0% on 4x4**, because it has to
invent a numbering convention for sixteen cells of one continuous photograph. If
you are building your own client, draw the overlay — see
[performance.md](./performance.md).

---

## Reproducing the browser figures

The example that produced them ships in this repo:

    cd js && npm run demo

It drives the vendors' own demo pages through the hosted API and prints two
clocks per attempt: the solve span, which is what the medians above measure, and
the total, which adds page load and the demo page's own reveal click.

The static-image figures are measured against a held-out corpus of real captures
that is not distributed. The method is stated above in full, so its shape is
reproducible against your own captures.
