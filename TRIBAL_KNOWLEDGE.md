# TRIBAL_KNOWLEDGE.md

Decisions taken in this repository, and why. Not a changelog and not a design
doc — the things a new contributor would otherwise learn by breaking something.

---

## Layout and publishing

**One repository, three published packages.** `js/` is the browser driver on
npm, `python/` is the engine and CLI on PyPI, and `mcp/` is the account server on
npm. They ship together because the two solver ports must behave identically:
`contract.json` records both public surfaces and a new divergence fails the
build.

**The JS driver bundles the Python engine instead of reimplementing it.**
`js/scripts/copy-python.mjs` copies repo-root `python/` into `js/python/` at
build time, and the driver shells out to that CLI for grid detection and
prompting. npm can only pack files inside the package root, so the copy exists
purely to satisfy packing — the single source of truth is the repo-root
directory, and `js/python/` is gitignored.

**The MCP server is deliberately not a dependency of the solver, and has its own
version line.** Signing in and minting a key is a one-time onboarding path; the
solver client has a handful of runtime dependencies and should not pull the MCP
SDK and a schema library on every browser-driver install. Tying the version
numbers together would also mean cutting an MCP release every time the solver
changed.

**Each published package carries its own `AGENTS.md`.** Whoever runs `npm i`
gets `js/` and nothing above it; whoever runs `pip install` gets the package
directory. `js/package.json` lists the file under `files`; the wheel
force-includes `python/AGENTS.md` because it sits beside `pyproject.toml` rather
than inside `src/captchakraken/`, and a wheel carries only the package.

**`AGENTS.md` is the product's documentation; `CONTRIBUTING.md` is the
contributor's.** Other people install this repo, so a consumer's agent loads
`AGENTS.md` from inside *their* project, where "branch off `dev`" and "delete
dead code when you find it" read as instructions about code that is not ours.
`CLAUDE.md`, `.cursorrules` and `GEMINI.md` therefore point at
`CONTRIBUTING.md`, which is also where the ecosystem already looks and where
GitHub surfaces it on every PR.

## Branches, gates and releases

**`main` only ever takes a merge from `dev`, enforced by a workflow rather than a
setting.** Branch protection can require a PR and require checks, but it has no
rule for which branch may be the *source* of a merge — so the one property that
describes this project's release flow is the one GitHub cannot express, and a
required check is the only place to put it. There is no bypass inside
`promote.yml` on purpose: a check with its own escape hatch is a check that gets
escaped.

**The version number does not identify the build, so the release is tagged by
the job that publishes it.** Manifests are bumped when a release is OPENED, not
when its content lands, so every commit from the bump to the merge reports the
version that eventually ships. Measured across 3.1.0: the pre-fix commit and the
published one both read `3.1.0` in `js/package.json` AND `python/pyproject.toml`,
six commits apart. "What version am I on" is the first question anyone asks and
it returns the hoped-for number either way, so it cannot be the answer. The tag
is created in `publish.yml`, beside the publish, which is the only place that
knows which commit actually shipped. It is idempotent and asks the REMOTE
whether the tag exists, because that job's checkout is shallow and carries no
tags of its own.

**A push to `main` publishes, so `main` is the most irreversible branch here.**
`publish.yml` fires on push and puts both ports on npm and PyPI within minutes,
at a version number that can never be reused. There is no rollback for a
publish, only a higher version.

**Publishing is tokenless, via OIDC trusted publishing, and idempotent.** No
registry secret lives in this repo to leak or rotate, and a version already on
the registry is skipped rather than failed, so re-running a half-finished release
is safe. The one exception is a brand-new npm package: trusted-publisher settings
live on the package page, so the very first publish of a new name needs a one-off
manual push before the automated path works.

**CI runs on pull requests into `dev` as well as into `main`.** It did not, and
work therefore landed on the integration branch ungated and first met CI at the
`dev → main` promotion — where a failure blocks the *release* instead of the
change that caused it. The jobs are hermetic and Actions minutes are free on a
public repo, so there was never a cost argument for the narrower trigger.

**The Python suite runs whole, not from an allowlist.** A hand-picked list of
four files silently skipped tests that existed, passed locally and gated nothing.
If a test is too slow or not hermetic for CI, mark it skipped so the skip appears
in the run output rather than being invisible in a workflow file.

**A pull request here is gated on driving, not on solve rate.** This repo ships
the driver, so a PR cannot change the model; what it *can* break is a selector, a
click landing off-widget, or one port asking for something the other does not.
The fixtures are not in this repo, so `tier3-request.yml` asks the repository
named by the `GATE_REPO` variable to run that gate against the PR's exact commit
and post back a redacted result — a commit status and per-port, per-vendor pass
rates, and nothing else.

**That dispatch uses the REST endpoint directly, and the gate repository's
address lives in a variable.** `gh workflow run` looks a repository's default
branch up first, purely to pick a ref for you, which costs a metadata permission
the dispatch itself does not need. A public workflow file is also not the place
to write down where a private repository lives.

**A fork's PR cannot run that gate, and that is the design.** `pull_request`
never exposes secrets to a fork's own workflow run, so no dispatch token can
reach untrusted code; the check simply sits pending, and a maintainer re-runs it
by pushing the branch into this repo.

## The model contract

**Prompts belong to the model, not to a client release.** A model answers in the
schema it was trained on, and when the shipped prompt drifts from it nothing
errors — puzzles just fail silently. So `models.json` records which prompt
generation every published model was trained on, and `prompts.py` ships the
built-ins for every generation still in service; hardcoding one generation makes
drift inevitable, because updating the constants breaks already-published models
and not updating them breaks the new one.

**`keyframes.py` must slice exactly as the training-side extractor does, and
must not be improved here.** The model is trained on keyframes cut by that
extractor and answers with a frame *number* indexing into them, so if this copy
sliced a recording differently the number would name a picture that does not
exist and the driver would wait for a state the page never reaches. Its
region-diff metric is reused as the driver's wait-for-state gate, so the two
agree by construction. Until the 2026-09 code cut the two files were
byte-identical and the training repo's parity gate compared them byte for byte;
this copy is now comment-free and enum-typed, so that gate has to be re-synced
on the training side to compare behaviour (the fixtures in
`test_keyframes*.py`) rather than bytes. Every threshold in the file was
measured, not guessed, and the measurement now sits beside each constant.

**Grid screenshots are sent with cell numbers drawn on them.** The client runs
`find_grid`, has `overlay.py` render the numbered labels, and sends that image,
because the model reads those labels and was never trained to invent a numbering.
Skip the overlay and reCAPTCHA 4×4 scores zero without raising anything — it
looks exactly like a broken model.

**`find_grid` is pure OpenCV, with no model in it, and is the most heavily gated
code in the repo.** Every grid solve rests on it, and each geometry gate exists
because a specific false positive happened: a lattice whose gutters separated
nothing, a shape no vendor ships, a footer counted as a row. Read the test named
for the gate before changing one.

**One page carries every published number.** `docs/benchmarks.md` holds the
end-to-end browser counts and the static-image rates, deliberately as counts
rather than percentages, because the two measurements answer different questions
and a single blended percentage answers neither. Nothing anywhere else in the
repo may derive, round or convert one of them.

**The version is one number in three places.** `python/pyproject.toml`,
`js/package.json` and `captchakraken.__version__` are compared by a test because
they drifted once: the runtime attribute said one release while the wheel on PyPI
said another, so every caller branching on it — and every bug report quoting it —
named a version that had not been current for weeks.

**Resampling is greedy-only, by measurement.** `RESAMPLE_TEMPERATURES` is
`(0.0,)`. Trying `(0.0, 0.35, 0.7)` on repeated answers scored 0/5 against 4/5,
and the median failed attempt cost 24.0 s against 13.9 s: making each re-ask
differ resets the no-progress counter, so the attempt stops bailing at round 3.
The level and seed plumbing stays for a network-refusal trigger. The driver
sends the resample LEVEL, never a temperature, so the schedule lives in one
place and the two ports cannot drift; the CLI is a fresh process per round and
cannot know the round count.

**`BUILTIN_PROMPTS`, `AVAILABILITIES` and `PROMPT_FAMILIES` are pure literals,
and stay strings even though `kinds.py` has the enums.** The training repo's
release parity gate reads them by AST without importing the package. An
f-string, a `.join()`, a constant reference or an enum member reads as "unset"
to that gate, and the gate going quiet is how prompt drift shipped on
2026-07-18: every drag failed as "unsupported" with CI green.

**The pin decides the registry entry.** Reading `base_model` and `lora_name`
off `latest` while `CAPTCHA_LORA_ADAPTER` named Abyss-27B downloaded a 9B base,
tried to load a 27B adapter onto it, and errored deep inside vLLM as a shape
mismatch. An unregistered pin still falls back to `latest`, for self-hosters.

**The hosted default is the routing alias, never an arm, and only against an
exact host list.** `abyss-general` is a lone expert that declares no `experts`,
so sending it pins every family to the generalist silently. "Is it remote" is
the wrong test: a self-hoster's vLLM across the network is remote too, and
asking it for the hosted-only model is a 404 on every request. A missing or
broken registry falls through to `pinned_model.json`; it never throws.

**An unknown prompt family degrades to the generalist; an unknown pin raises.**
The day the generation-2 `text` family reached ckgate without a marker,
refusing it cost every distorted-text solve in production for a day. The other
way round, a benchmark that silently measured the generalist under a bad pin is
a number nobody can catch. `private` is not a softer `licensed`: refusing early
on a licensed model replaces a `RepositoryNotFoundError` that reads as "you are
not logged in" with the truth, but doing the same to a private model would stop
our own admin token from pulling weights it is entitled to.

**`MIN_PIXELS` is a floor on area, not a resize.** On a 277x285 GeeTest board,
predictions landed 80-105 px from the hand label at native size and 1-4 px once
upscaled. The area is clamped rather than the dimensions because squashing the
aspect moves every tile centre.

**`X-JH-Priority` is a header, not vLLM's body `priority`.** The body field is
lower-is-higher and already means captcha=0 / apply=100 / label=200 on the
priority-scheduled primary, so a 10 there would misorder. The gateway routes
values above 5 to backup GPUs; tier-2 CI sets 10. Every routing header is
derived independently so a malformed priority cannot suppress the attribution
headers and understate a partner's revenue share, CR/LF is stripped so nothing
can splice a header, and caller-supplied headers can never rewrite
`X-CK-Session`: pinning one session id forever would escape the per-attempt
billing cap.

**Thinking is switched off with both spellings.** Ollama ignores
`chat_template_kwargs.enable_thinking` and defaults thinking on; vLLM derives it
from `reasoning_effort` only when the kwarg is unset. Sending both is the only
way one request is right on every runtime.

**`--enable-tower-connector-lora` is required on `vllm serve`.** Without it
vLLM silently drops the vision-tower half of the LoRA and grid accuracy
collapses, with nothing in the logs.

## Client details that cost a real diagnosis

**`python3` is tried before `python`.** On Debian-family systems there is no
`python` on `PATH` at all, so every JS solve died with "python: not found" before
it ever reached the model — and because the Python client obviously ran, it
looked like an endpoint or model problem rather than a missing binary.

**The package defines its own structural `Page` type instead of importing a
browser's.** That is what lets the driver accept any Playwright-compatible
launcher and install no browser of its own; a real dependency would pick the
launcher for the user.

**Tests are selected by a tsconfig, not by a list of filenames.** The old `npm
test` named every test and every module it imported, so adding a test meant
editing that list and a test left out of it silently never ran — which had
already happened.

**A puzzle-piece slider is aimed once and then corrected, not calibrated
first.** The distance between the piece and the slot is already an estimate of
how far the handle has to travel, so the drag opens with one sweep at the gap —
the gesture a person makes, and one move and one screenshot cheaper than the two
measurement nudges it replaces. What the nudges were really for is the piece's
width and the handle-to-piece ratio, and the sweep supplies both better: it
carries the piece clear of the ground it vacated, leaving two separate marks in
the frame, and the right-hand one IS the piece. Measuring it beats inferring it
from the union of the two, whose width is the piece plus a travel that is only
believed.

**The piece does not always start under the handle, and a sweep aimed from the
handle can push it off the board.** One vendor's handle sits 42px into a 360px
card while its piece sits 136px in, so aiming the handle at a slot 288px across
sends the piece to 382 — past the edge, where the only thing left to photograph
is the ground it vacated. `locate_piece` reports that for what it is, a mark
narrower than the distance travelled, and says where the piece went; the next
correction brings it back. Reported instead as "nothing moved", it is
unrecoverable: the loop looks again, sees the same thing, and lets go with the
piece off the board.

**Nothing may be written to stdout by the MCP server.** On the stdio transport
stdout *is* the protocol channel, so one stray `console.log` — a banner, a
deprecation notice — corrupts the stream and the client reports the server as
broken rather than as chatty. Diagnostics go to stderr, which clients surface in
their logs.

**A minted API key is written straight to a `0600` file and never returned
through the conversation.** The obvious move for an agent is to echo the key it
just created, and a transcript is not a secret store. `create_api_key` reports
only the path, and the solver reads that file with no environment variable set.

**Tencent moved its widget in-host on 2026-08-11 and the client said "no
captcha" for twelve days.** It left the iframe and renamed every class while
`captcha.gtimg.com` never left the wire. `VENDOR_URL_MARKERS` is the tripwire
that came out of it: a vendor host loaded with no selector match is reported as
"the markup moved", not as "no captcha". Both the in-page and the iframe
selector shapes are kept, and `iframe[id^="tcaptcha"]` is prefix-anchored
because the substring form also matched MTCaptcha's `mtcaptcha-iframe-1`, which
made Tencent's entry silently the only thing detecting MTCaptcha and hid that
`.mtcap` matched nothing. BotDetect is absent from the markers on purpose: it
is self-hosted and has no vendor host.

**Yandex and MTCaptcha are iframed.** `.CheckboxCaptcha` and `.mtcap` live
inside the frame document and `querySelector` does not cross a frame boundary,
so on the host page those entries matched nothing, ever. Iframe selectors go
first; the class entries remain only for inline embeds. The same login-form
hazard orders every selector table vendor-first and scopes the answer-box
search to the widget's fieldset or form: a generic `input[type=text]` outside
the widget is exactly how a captcha's answer ends up in a username box.
`VENDORS_WITH_BESPOKE_HANDLING` is spelled as a set rather than `== "unknown"`
because naming a new vendor would otherwise silently switch off typed-challenge
detection for MTCaptcha, Yandex and BotDetect and the animated probe for
GeeTest and Tencent, and neither failure throws.

**GeeTest's acceptance is inside the panel, and the panel closes.** Success
paints inside the open panel with no token, and `geetest_popup_wrap` carries
the same class at zero height while shut, ahead of the real banner in document
order; 20 drags cost 34 model calls before visibility became part of the test.
`done` must need no bounding box, since the widget is gone on accept: 22 of 22
across four puzzles died there and were banked as model errors. The OK control
is `<div class="geetest_submit geetest_disable">OK</div>` beside tooltip decoys
that also say OK; it scored 0/31 and then 0/13, which reads exactly like a
puzzle the model cannot do. Pin the finder, not a rate.

**The eight inline vendors are part of the "is there a widget" DOM probe.**
Without them the JS port failed fast in under a second on every GeeTest, Yidun
and Tencent page and the two ports disagreed in Tier 3. A drag starts on the
HANDLE, never the piece, which is inert decoration, and `[draggable=true]` is
deliberately absent from the handle list because HTML5 drag-and-drop fires
`dragstart`, not `pointermove`.

**The API key rides in the environment, never argv.** Argv is world-readable
on Linux: any local user can read `/proc/<pid>/cmdline` or run `ps` while a
solve runs. Arguments go to `execFile` as an array, never a shell string. The
CLI's `model` and provider positionals are passed both-or-neither, because the
provider alone binds to `model`.

**Credentials precedence is env, then file, then localhost, and a bare token
carries no endpoint.** A camoufox user who signed up through the MCP had a
valid key and no endpoint, so every solve dialled a local port. The bare-token
file format stays because dropping it breaks every existing credentials file;
it yields no endpoint because that would silently redirect a self-hoster who
hand-wrote a local key.

**`errors.py` owns the wording; the JS port repeats it verbatim.** Before it
existed, a camoufox user out of credits read `vLLM 402 Payment Required at
https://api.captchakraken.com/...`. Branch on the code, never the message.
Unknown codes carry the server's message through so a new code is never
reported worse than the known ones; a `Retry-After` HTTP-date is dropped rather
than guessed. The JS
`parseApiError` scans stderr line by line because timing records share the
stream, and returns null for anything unrecognised: an unparseable stderr must
not become a confident but wrong billing message.

**The watcher injects nothing.** An exposed binding is a function on `window`
and a `MutationObserver` is script the page can enumerate; under Camoufox both
are sandboxed and invisible, under vanilla Playwright, patchright or Puppeteer
they are not, and a captcha vendor is exactly the party that looks. Polling
`detectCaptcha()` lands in Camoufox's isolated Juggler world for free because
it never opts into the main world. Detection reuses `detectCaptcha` because an
earlier copied selector union drifted from `SELECTORS` the first
time a vendor was added. The Python watcher blocks because a sync Playwright
handle is bound to the greenlet that created it. After a raise it backs off
(5 s) so a permanently unsupported challenge does not re-attempt and re-bill
every tick forever, and "no captcha" is never a failure or the first tick would
sleep.

**Humanisation is an interface because two humanisers compose badly.**
camoufox's `humanize` juggler re-humanises every `mouse.move()` it is handed,
and running ours on top measured 82.1 s against 13.4 s on one GeeTest v4
slider solve. A touch widget needs touch events: dispatching mousemove there is
the wrong event type, the page's touch handlers never fire, and the report
reads as a model that cannot solve mobile puzzles. Mode precedence is code,
then env, then mouse, the opposite of the model-identity settings, because an
env var flipping a desktop solve to touch dispatch would break every one
silently. Both mouse humanizers clamp the path to the window only when they
know the window: camoufox opens its context with `viewport: null`, so
`viewportSize()` is null and the window is asked for `innerWidth`/`innerHeight`
instead; a coordinate pinned to the edge of a guessed 1920x1080 is what
deadlocked its juggler (upstream #225), and the JS port carried that guess until
2026-09-14. Typing is per character with a drawn delay, never `type(text,
{delay})` or `fill()`: a constant inter-key delay is itself a signal and these
are the vendors that score typing cadence.

**`PhaseBudget` is always collected and printed only under
`CAPTCHA_TIMINGS=1`.** A budget you have to opt into is one nobody has when
the slow solve happens. Phases attribute rather than partition: a nested phase
counts under both names and re-entry counts once.

## Grid detection

Every constant in `find_grid.py` was measured on the real capture corpus, and
the number now sits beside it. What follows is the reasoning that does not fit
on a line.

**The colour comb and the seal test are `find_grid`'s second cue.** The tracer
is a local walk and loses a gutter whose neighbours are nearly its colour: on
one capture, pure-white gutters at x=103/200/297 came back as 66/96/215. The
comb asks whether a whole straight line is the gutter colour end to end; the
seal asks whether every separator of a candidate lattice runs its full extent.
Both only ever look for a colour the tracer already proved painted, so neither
can conjure a lattice from a flat image. Measured over 1423 real grid captures:
misses 15 to 3, end-to-end false positives 23 to 16. The comb wins on position
only and takes its extent from the trace (it once reported a full-width 520 px
gutter as a 43 px stub), and the page margin is dropped at the comb source or a
3x3 is reported as a 4x3. `SEALED_FLANK_MIN_DE = 6.0` admits 86 geetest_v4_svg
line-art boards that all die downstream in `_is_real_grid` by 0.31, so it is
free on the false-positive side; at 8.0 two real sky-backed 4x4s (which measure
6.x to 7.1) stayed undetected.

**Noisy gutters: tolerances scale with the measured noise floor; they are not
widened.** Bridging bad pixels took the fixtures from 3/20 to 10/20 but
collapsed real reCAPTCHA 3x3 from 40/40 to 7/40. Flat wider thresholds of 10/8
for `SEED_L`/`STEP_L` cost one pristine sample and 14/12 cost four. Scaling
leaves a compositor-painted gutter (noise about 0) at exactly the old
thresholds: 13/20 fixtures, corpus 144/144, false positives 6/355 unchanged.

**Flank contrast is a mean over both sides, gated on the chosen grid only.**
Under `min` the lowest true hCaptcha grid scored 2.7 against false positives at
9.0 and 7.2, so no cutoff existed; the mean gives 17.4 against 18.0 and 14.1.
Applied as a per-line filter it removed the strays the off-lattice gate counts
and false positives went 2, 4, 6. The probe distance scales with pitch because
a fixed offset landed inside hCaptcha's 13 px gutters and read gutter against
gutter as zero contrast.

**`_pick` takes the gutter colour from the cleanest comparable-support member
of a cluster, not the longest trace.** On 2026-08-11 an ice-cream board kept a
trace 11 px off the gutter on a watermark, colour std 2.80 against 0.55-0.80
for the on-centre traces, which withheld the `CLEAN_GUTTER_STD` relaxation and
failed a correct 3x3. Nearest-to-centre instead swapped a 0.00 trace for a 3.43
one on a reCAPTCHA capture, so it is cleanliness among comparable support.

**`_corroborate` estimates the pitch over gaps at least `MIN_CELL` wide but
guards on the raw median.** Comb-reported footer bands took a 3x3's pitch from
87 to 55.8, the bottom border corroborated, a 4x3 won and died on
`_boxes_are_regular` with no fallback: 20/20 to 5/20 on one generator.
Filtering before the guard instead skipped the perpendicular rescue and cost a
reCAPTCHA 4x4 its fourth row (raw 34.5, filtered 80.9, perpendicular 97.0, and
only the last is the cell).

**Candidate scoring has three asymmetries, each from an incident.** The unused
count is clamped at zero per axis, which is how a half-pitch 5x4 once outscored
a 4x4; only sealed lines count as unused; the virtual-node refund applies to
interior nodes only, because the true 4x4 on every sky-backed reCAPTCHA lost by
about 470 without it and an extrapolated refund turned a correct 3x3 into a
3x4. `UNSEALED_PENALTY` (700) must exceed `UNUSED_LINE_PENALTY` (400) or a sky
belt outscores the true lattice. The off-lattice gate counts clusters with a
20 px window because the plateau on the corpus is 17..23 (1091/1106 targets at
2/458 false) and at 24 a textured drag puzzle becomes a false positive.

**`MIN_IMAGE_AREA_COVERAGE` is 0.348 and deliberately not 0.33.** It was first
named `MIN_GRID_COVERAGE`, which already existed, so the area check silently
ran at 0.72 and detection went to 0/2210 across the corpus. 0.33 would also
catch an observed video-keyframe false positive at 0.322 but leaves 5%
headroom; the floor is measured over 2239 real grids.

**The hCaptcha selected-badge detector requires white within 2 px of the teal
hull.** Sky with a white pole in it satisfied the old test: 74 phantom
selections over 3051 corners. Zero slack fragments ringed renderings; 4 px
doubles the phantoms back to 32 for 1.2 points of recall. The phantom budget in
the test (0.012) is a ratchet set so the previous release fails it: on
2026-09-06 over 118 boards this tree measured 1.13% and origin/main 1.41%, and
the old 0.005 was against a corpus a third the size. Re-record both arms on the
same corpus in one commit, only ever downward. The residue is all one class,
blue sky plus something white.

## Rounds, bursts and gates

**The board paints before the round asks anything about it.** A round opens on
two questions — which expert answers it, read out of the DOM as "is there a text
box in here", and whether the board cycles, read off its motion — and both were
asked at the top of the round, before the widget had necessarily drawn. A
resolved vendor frame holding nothing answers both wrongly in the same way: no
box to find, and no motion but its own arrival. The paint wait is not new and
was not added for this; it already ran a few lines further down, and it moved
ahead of the two decisions that depend on it. Anything that wants to know what
the board IS goes after it.

A reCAPTCHA round is the exception, and it is not a special case so much as the
same rule read the other way: it is asked neither question — never typed, never
filmed — and it waits for its board at the grid gate, on the cells themselves.
Waiting for the paint in front of that gate measured 0.8-1.8s a round on the
family with the tightest per-board budget, and covered a board the gate below
already covers.

**A verdict is read off the film, not off the clock the film ran on.** The
speculative round films the widget while the model reads one screen of it, then
asks the film whether the board moved. The ask is what takes the time, so on a
slow round the recording is over before it is questioned — and a verdict that
only ever read a film still rolling called every finished one a still. The
Python port never had this: its burst is synchronous, so it computes its verdict
at the end of its own window. The JS recorder now answers the same way.

**The blank-board gate exists because the settle gate cannot see a blank
rebuild.** Measured on gt4.geetest.com's slide demo on 2026-09-12 over ten live
attempts: six of fifty-two requests carried a board with under 5% ink and every
one answered dead centre. A blank panel is perfectly still, so stillness cannot
catch it. The gate measures structure (share of centre pixels off the modal
grey), not ink, because geetest_v4_svg is line art on white; from the centre
box, because caption and icon chrome paint early; floor 0.015 against 0.000 to
0.004 blank and 0.19 to 0.56 painted. A `False` means wait, never give up: a
gate that can refuse to ever take a picture is worse than the blank picture.

**Bursts are filmed with `animations: 'allow'`.** Playwright's `'disabled'`
freezes infinite CSS animation, so bursts sliced GeeTest svg to `mode=static`
forty identical frames at a time; hCaptcha hid the bug because it animates in
canvas. `shot()` defaults to `'disabled'` and exactly three sites pass
`'allow'`: the burst, the keyframe wait and the freshness anchor.

**`MOVED_DURING_INFERENCE_DIFF = 0.002` is a separate, tighter number than
`staleFrameDiffThreshold` (0.02).** At 0.02 the guard was blind to GeeTest svg;
0.001 is the noise floor. Third time this file applied a coarse threshold to a
fine question.

**`BURST_ANIMATED_SCREENS = 6`.** hCaptcha odd-animal measured 38 distinct
screens in 4 s with no repeat; past 6 (which equals `DEFAULT_MAX_KEYFRAMES`)
there is already more motion than a keyframe answer can describe. The read is
safe only because the speculative burst does not wander the cursor: one live
burst reported a dozen screens that were the mouse. reCAPTCHA is never
speculated because its dynamic 3x3 replaces tiles in place and a burst there
films a fade and calls it a cycle.

**The keyframe wait moved from 6 s to 9 s, and the animated budget hangs off
it.** GeeTest svg dwells up to 2.7 s per screen, so a three-screen cycle is
8.1 s worst case and 6 s gave up one screen short however well aimed.
`videoBudgetMs` is derived from it on both ports, and a JS test once pinned a
local `6_000` that kept passing after the default moved. The budget is granted
once per solve (per burst would be unbounded), sized from the burst ceiling (a
4 s window cannot contain a 5.3 s cycle), never abandoned partway (stopping at
frame 27 of 40 gives a recording that may not contain the screen), and refused
before recording with the knobs named. The burst hang detector must be slack
against the work it supervises: 16 of the Python port's 69 failed attempts in
one run were it firing on a still board. There is no "enough screens, stop
filming" exit: both spellings were measured on number_with_highest_value_video
and failed every seed either way.

**The second look is a question, and the clip it records answers it.** A board
that failed a round buys one recording, because "settled" is not proof of
static. That probe used to declare the board animated *before* filming it, so an
ordinary miss on a still board — a slide landing 3% wide, a grid read wrong —
went to the video expert, which can only answer a still with a frame number no
widget will take. The answer then repeated until the no-progress fence tripped:
three rounds and twenty-three seconds where one re-ask would have done, and a
board that needs a second drag never got one. The clip decides now, and it may
only PROMOTE: an animation the settle classifier already measured is never
demoted by a film that ends on a settled screen, which is exactly what a board
that plays once and stops films like.

**The camera does not stop when the answer is sent.** A burst can only show the
model the screens that fell inside its window, and the answer it produces is
identical next round by construction: sampling is greedy (`RESAMPLE_TEMPERATURES
= (0.0,)`), so the same frames give the same answer. A board whose answer lived
on a screen the window missed therefore had no second chance — the stored plan
was re-pressed until the no-progress fence tripped at round 3 of 6, with half
the budget unspent. Measured live on 2026-09-15 against the vendors' own pages,
hCaptcha's animated board read **2/15 and 6/12** on the two served models, where
the driver that still re-filmed every round had recorded **36/36**. Re-filming
had been retired as a defect — it did exhaust the budget — without anyone
noticing it was also the only retry an animated board had.

So the film now runs for the whole solve and every round slices a **strictly
longer** one. This works because a keyframe is a distinct SCREEN, not a frame:
`_detect_cycle` returns one representative per screen in the cycle, so a longer
film converges on the cycle instead of growing the request, and on a board that
never repeats `_even_indices` spreads its six picks across the whole solve
rather than across four seconds. A refused answer drops the PLAN and keeps the
film; only a board that is gone stops the camera.

**The two ports accumulate differently, and that is not a divergence to fix.**
The JS recorder is an async loop on the solver's own event loop, so it films
continuously — through inference, through the verdict wait — and pauses only
while we click, because a frame of the board wearing our own answer is not a
screen the board ever showed. Sync Playwright is thread-affine, so the Python
port cannot run a camera on another thread at all; it films another chunk each
round and slices the accumulation. Same contract — a refused animated answer is
re-asked against strictly more of the board — at a sparser sample.

**`measurePieceBox` must not set `actedOnBoard`.** It runs during detection,
and marking there disabled `shouldSpeculate` on every slide solve, so the
speculative burst had never run on those boards.

**`DEFAULT_RECAPTCHA_MAX_DYNAMIC_ROUNDS = 8` sits inside the gateway's comped
band.** Rounds 1-5 are billed, 6-10 served and comped, 11 refused with 409; 8
keeps a margin on both sides. If the billable cap moves, re-derive it and move
`limits.test.ts` in the same commit.

**The `[answer]` stdout line is graded by Tier 3 with Tier 2's grader.** That
separates driver bugs from model misses, and it is how a 2.5% drag undershoot
hid behind an 87% held-out score.

## The MCP server

**Nothing spends money without a human.** `get_topup_link` returns a URL. It
does not charge a card, and there is no tool that can.

**Two credentials in two files, nothing encrypted, keyed by base URL.** `ckm_`
can mint and `ck_live_` can only spend; one file holding both is a strictly
worse blast radius for no gain. Encryption at rest on a developer machine is
ceremony, not protection. The store is keyed by base URL so a dev token is never
silently presented to production. It is written to a 0600 temp file, renamed
into place, then `chmod`ed again because an existing file's mode wins on some
filesystems. XDG then `~/.config` on every platform, not `%APPDATA%`: one path
is easier to tell a person to delete than three. The endpoint is written beside
the key, since a key without one authenticates flawlessly against a local port
with nothing behind it. `CAPTCHA_KRAKEN_STATE_DIR` is honoured because the
Python client honours it.

**`SIGN_IN_WAIT_MS = 25_000`, and the device flow resumes.** Sixty seconds is a
common MCP client timeout and a sign-in that blocks for two minutes gets killed
with the device code stranded, so the tool returns `waiting`, persists the
pending code, and the next call resumes it. `slow_down` doubles the interval
permanently per RFC 8628 §3.5; an implementation that ignores it hammers an
unauthenticated endpoint. A 401 on an authenticated call drops the stored token
so the next `sign_in` is clean; device endpoints are exempt because they answer
400/401 for reasons that have nothing to do with a stored token. `sign_out`
revokes server-side first and keeps the file on failure, because the file is
the only copy.

**`get_models` reads each flag for what it says.** `hosted` and downloadable
are separate; deriving one from the other misreported Twilight and Abyss both
ways. There is no video line, on purpose: animated support is a generation
property, and on 2026-09-06 the control plane had Sunlight flagged false.
`AccountResponse` fields are optional for a control plane older than migration
0008; absent reads as "a normal account", which is the safe way to be wrong.


## Navigation, coverage and pins

**There are two maps, and only one of them is committed.**
`FILE_PURPOSES.md` answers "where does X live?" and is tracked, reviewed and
gated. `repomix-output.md` answers "does a helper for this already exist?", is
generated by `npm run repomix` in well under a second, and is gitignored — a
generated map that is committed goes stale and still gets trusted, which is worse
than not having one.

**The map is uncompressed, against the letter of the spec.** repomix's
`compress` mode keeps classes, functions and interfaces but drops plain
declarations: with it on, `js/src/limits.ts` came out as an empty code block, and
`grep -nE "const foo ="` — the search the rule actually tells you to run — found
nothing. Comments are still stripped. The map is 519 KB instead of 171 KB, which
costs nothing for a file nobody commits.

**The root `package.json` is tooling, and says so loudly.** repomix and the
codebase-map gate need a manifest, and putting them in `js/` would ship a
contributor's tools to every consumer of the published package. So the root
manifest is `private: true`, is published nowhere, is named in
`FILE_PURPOSES.md` as tooling-only, and is the first thing `CONTRIBUTING.md`
explains about the layout — because three manifests in one repo is already
enough ambiguity about which one `pip install` and `npm i` actually use.

**`FILE_PURPOSES.md` is now gated, in both directions, before any test runs.**
`.github/scripts/check-file-purposes.mjs` compares `git ls-files` to the table
rows and fails on a tracked file with no entry, an entry naming a path that is
gone, and a path listed twice. It has no dependencies so it can run before
anything is installed, and every test job waits on it: a missing row is one line
to fix, and discovering that twenty minutes into a test run is a waste nobody
chose.

**Coverage floors are set at what the suites measure, not at what the spec
asks.** A gate that is red the day it lands blocks every pull request and
teaches the team to bypass gates, which costs more than the gap it advertises.
The floors are the measured values rounded down (Python 69%, TypeScript 73%
lines / 80% branches after the 2026-09 code cut); they go up, never down.

**The Python floor is measured on the interpreters CI actually runs.** 3.10
reports 58.33% and 3.12 reports 58.31% — 0.02 of a point apart — so the
threshold runs on both legs rather than on one measured leg and one guess. The
first version of this was measured on 3.14, the only interpreter on the machine
at the time, and that habit is what produced the numpy break below; a real 3.10
environment (`uv python install 3.10`) costs two seconds.

**c8 and `node:test`, not Vitest and `@vitest/coverage-v8`.** The spec names
Vitest, and switching would mean rewriting 30 test files that currently import
`node:test` — a change to the tests themselves, which is not something a
coverage gate is allowed to smuggle in. c8 reads the same V8 coverage Vitest
would and emits the same lcov. The `sourceMap` flag in `tsconfig.test.json`
exists only so those numbers land on `src/*.ts` rather than on compiled output;
`dist/` is built by `tsconfig.json` and carries no maps.

**c8 runs without `--all`, and the new tests did not change that.** With `--all`
pointed at a TypeScript source tree every file still reports 0% — the synthesised
entries collide with the source-mapped ones, which is a c8 limitation rather than
a function of how much is tested. Without it a module no test imports would be
invisible, and the reason that is survivable is checkable rather than assumed:
comparing the report's file list against `src/*.ts` leaves exactly one file out,
`playwright-types.ts`, which is types only and emits no executable line. Re-run
that comparison when adding a module; do not reach for `--all`.

**`mcp/` has no coverage number because it has no test suite.** Its gates are a
type-check, a build, and a real MCP handshake against the built binary. A
percentage measured over a smoke test would describe nothing, and inventing one
to fill the column is worse than leaving the column empty.

**Codecov uploads are gated on the token; the thresholds are not.**
`CODECOV_TOKEN` does not exist in this repo yet, and on a fork PR it never will —
`pull_request` does not expose secrets to a fork's own run, the same reason the
driver gate cannot run there. So the upload step skips when the token is empty
while `fail_under` and `check-coverage` run unconditionally. A required check
that passes by not running is worse than no check at all.

**Every version is exact, including CI actions.** All four manifests pin `==` /
no-caret versions taken from what actually resolves and passes, and every GitHub
Action is pinned to a commit SHA with its release tag in a trailing comment —
`actions/checkout@…` was `@v4`, a moving tag that silently changes what runs on
every PR. A version changes through a reviewed PR or not at all.

**A pin must install on the floor the package promises, not on the interpreter
that pinned it.** `numpy==2.5.3` was chosen from a 3.14 environment and turned
the 3.10 leg red on arrival: numpy 2.5.x declares `Requires-Python >=3.12`, so
pip could not find any candidate at all. The fix is 2.2.6, the newest numpy that
still covers 3.10 — not raising `requires-python`, which would drop a platform
installed users are already promised and is a breaking change, not a pinning
detail. Every other pin was re-checked against 3.10 the same way, and the full
suite now runs green on real 3.10.20 and 3.12.13 interpreters before the pins
are believed.

REVERSED IN 3.0.0, and the reasoning above is why it took a major version to do
it. The floor is now 3.11. `cursory` — the recorded-trajectory mouse — declares
`Requires-Python >=3.11` and requires `numpy~=2.3.3`, which declares the same,
so 3.10 could not be kept by choosing a different pin: there is no version of
either that runs there. Dropping a promised platform is a breaking change, which
is exactly what a major version is for, and 3.10 reaches end of life in October
2026. The rule itself is unchanged and still the one that matters — resolve
against the floor `requires-python` promises, whatever that floor currently is.
CI's legs moved to 3.11 and 3.12 in the same commit, because a floor nothing
tests is not a floor.

**The map tool is pinned above the repo's own Node floor, deliberately.** The
packages and CI run Node 20; `repomix` needs 22 from 1.14.1 onward. Every
repomix that runs on Node 20 is covered by an unpatched command-injection
advisory, so the root tooling manifest declares `engines.node: ">=22"` and keeps
the patched version. It is a contributor tool, published nowhere and never run
in CI, so the cost is a clear `EBADENGINE` warning rather than a broken build —
and that is a better trade than shipping a known RCE to save a Node upgrade.

**The Python matrix does not fail fast.** A 3.10 failure used to cancel the 3.12
leg mid-install, so a run that should have reported "3.10 cannot resolve this
pin, 3.12 is fine" reported only the first half and left the second unknown. The
legs are minutes long and Actions minutes are free on a public repo; the
information is worth more than the cancelled runner time.

**The `serve` extra is pinned to vllm's own numbers, and cannot be verified
here.** `vllm==0.29.0` declares `torch==2.13.0`, so that pair cannot disagree.
Neither the pins nor the ranges they replaced resolve on a CPU-only box running
Python 3.14 — checked both ways — because the CUDA kernel packages have no wheel
for it, so this pin is no more fragile than what it replaced. Confirm it on a
machine with a GPU before the next release: `pip install --dry-run
"captchakraken[serve]"`.

## Residual, and deliberately not fixed here

**`python/Dockerfile` bases on a torch 2.7.0 image while the `serve` extra
installs 2.13.0 over it.** The old range did the same thing, so this is not new,
but pinning made it legible. Aligning them is an image change with a real GPU
test behind it, not a docs pass.

**The two v1-architecture test files are gone, not skipped.** They imported a
module that is not in this repo, so they could never run under any condition; a
visible `importorskip` was an improvement on silence but it was still a green
check over nothing. Deleted rather than ported: the v1 planner they exercise no
longer exists here.

**The grid-detection corpus of real captures is not in this repo.** The tests
that measure detection rates over it skip when the directory is absent, which is
the case in every clean checkout, so the hermetic gate covers the geometry rules
rather than the rates. It is also part of why the Python floor is where it is.

**Dead code was carrying part of the coverage gap.** Removing four unreferenced
`find_grid` tracer helpers, three unreferenced overlay drawing functions, a
prompt builder that duplicated `prompts.py` while hardcoding the newest
generation, a leftover `promisify(exec)` in the TypeScript solver, and nine
unused imports moved Python coverage from 53.45% to 54.74% without a single new
test — those lines were uncovered because nothing called them. Two rules made it
safe: an exported symbol is published API and was never a candidate, and every
deletion had to be unreferenced across `git ls-files` AND across the installed
consumers on this machine.

**Test output is kept out of the published package by the bundler, not by the
test.** `python/tests/test_solver.py` writes debug PNGs to `latestDebugRun/`
relative to the working directory, and `js/scripts/copy-python.mjs` whitelists
`python/` wholesale into the npm tarball — so before this was fixed, running the
suite and then building would have published a coverage dump and a folder of
debug images. Both are now skipped by the bundler and gitignored; the test still
writes into the tree, which is where it should be fixed.

**Three advisories against the MCP SDK's transitives are left open, because the
vulnerable code is never loaded.** `fast-uri`, `hono` and `qs` arrive under
`@modelcontextprotocol/sdk@1.30.0`, which is the latest release, so there is no
upgrade to take. They reach us only through the SDK's HTTP transport; `mcp/src`
imports `StdioServerTransport` and nothing else, so that transport is never
constructed and those packages are never on a code path this server executes.
We deliberately did not add npm `overrides`: forcing a transitive to a version
its parent did not choose is an upgrade rather than a pin, and this is the one
package with no test suite to catch what it breaks. Re-check when the SDK
releases.

**A grid is a lattice, and the detector was only ever asked what was inside the
cells.** `find_grid` traces separator lines "of any border colour and small
tilt" and recovers the slant on its own, so a TILTED lattice is one of its
legitimate outputs. No vendor ships one — every grid we solve is laid out with
CSS, on the pixel — so that tolerance is headroom no true board needs and a
photographic backdrop's own edges walk straight through it. `_is_real_grid`
then passed the result, because every check it had asks about cell CONTENT
(colour spread, the shared-background test that tells a sprite board from
tiles) and a click puzzle drawn over a photograph answers all of them honestly.
A grid answer is a LIST OF CELLS, so the mis-route does not read as a wrong
answer; it reads as the driver pressing six things on a board whose answer is
one press. The shape check now runs first and costs nothing — it needs no
pixels. Measured over the real captures, six per family: every true grid the
detector finds is regular to the pixel (25 detections, all 0.000) against 0.128
for the false one, so the bar is a floor with a 2x margin rather than a tuned
number. It is not zero only because an antialiased separator traced on a 100px
cell can honestly land a pixel out.

**Filming while the model is asked is only free if the camera stops first.**
The speculative burst reads the still and records the widget at once, and the
claim that makes that free is that the recording happens inside a wait the solve
was making anyway. It did not: the settled exit waited on the inference as well
as on the board, so once a board had shown one screen and held it for a full
floor window — nothing further to learn — the loop went on screenshotting at
10 fps for as long as the model took. Measured on a still GeeTest 3x3 photo grid
that broke the 20 s board ceiling: one distinct frame in 120, and the burst
still ran its whole 12 000 ms because that one model call took 22.6 s. The JS
port never had this — its burst breaks on the settled window alone — so the same
board reported `burst 1.5s` + `inference 1.8s` there and `burst 12.1s` plus a
10.4 s hole here. The hole was the second half of the bug: the post-burst wait
for the answer sat outside every phase, so the largest cost on a slow board was
attributed to nothing at all and the report read as "the burst is slow".

**The burst's windows are milliseconds, and were counted in frames.** "A burst
must outlast one full cycle" is a claim about SECONDS: the floor is what makes
the still verdict sound, because it is longer than the longest dwell a cycling
board holds a screen for (max 2.7 s measured on the GeeTest svg board). Both
loops expressed it as `video_burst_duration_ms / (1000 / fps)` frames instead,
and the two only mean the same thing while the loop reaches `video_burst_fps` —
which it does not when a screenshot costs more than the interval. There is no
frame-dropping: the loop sleeps `interval - elapsed`, so a slow camera simply
runs long, and the window stretches by exactly the ratio.

Measured on one element screenshot, same fixture, same box: 15.8 ms through the
desktop browser against 183.5 ms through Chromium at a phone's device pixel
ratio of 2.625. It is the DPR and nothing else — the same viewport and touch
emulation at DPR 1 costs 66.6 ms — so a 40-frame floor meant 4.02 s on one
driver and 8.25 s on the other, for identical evidence, while the inference it
overlapped had finished at 2.15 s. The same ratio scaled the 12 000 ms ceiling
to 20-31 s, which is a whole solve budget on a board that never moved.

The frame count was wrong in both directions, and the regression tests pin
both: a fast camera reached the floor's frame count in 400 ms of a 500 ms
window, so it also cut the clip SHORT of the dwell the window exists to
outlast.

`burst_hang_deadline_ms` keeps its 3x margin. It stopped being a budget for a
slow loop the moment the loop bounded itself in wall-clock, and is now only
what it says it is: headroom for a single screenshot that never returns.

**The rate a burst reports is the rate it achieved.** The slicer dates frames
by it, and a clip logged as "40 frames at 10fps" that actually ran at 5.4 is
what kept the stretched window out of every log and every phase report. It
moves no frames — the slicer picks by index and uses the rate only for
timestamps — so this is honesty in the manifest, not a change of behaviour.

**Re-asking the same pictures is arithmetic, not a retry.** A refused animated
answer drops the ANSWER and keeps the FRAMES, which is right for a cycling
board: the frames do not change, the answer merely landed on the wrong screen.
It is wrong for a clip the slicer could not find a steady screen in.
`steady_screens` counts the screens the clip can be PROVEN to come back to, and
zero means a continuous animation — the keyframes are arbitrary slices of
something that never holds still, the frame number refers to nothing, and the
same question about the same pictures returns the same answer until the solve
dies on `max_no_progress_rounds`. Resampling does not rescue it: a temperature
moves the coordinate a little, not the reading. Those clips are now thrown away
on refusal, which is what lets the next round re-classify a board that has
stopped moving as the still it now is.

**`PIECE_SELECTORS` is a second vendor surface, and it fails silently.**
The widget selectors failing is loud — nothing is detected. The piece list
failing is not: the driver falls back to measuring what moved between two
screenshots and solves anyway, so the pass rate does not move and no gate can
see it. Re-measured against the live vendor demos 2026-09-13 and it had two
defects. Tencent's piece carries a real, stable, vendor-named class that matches
none of the generic patterns, so every live Tencent slide had been taking the
fallback. And on Yidun the generic `[class*="jigsaw"]` matches TWO elements, the
first in document order being the widget's own container — five times too wide
and never moving — so "first visible match" would have handed the correction
loop a number that cannot change. The lookup now takes EVERY match of each
selector and keeps the first that could BE a piece, using the same size bound
the geometry path already throws a measurement out on. GeeTest has also started
stamping a per-build hash alongside the plain class; the plain one still matches
today, and the day it stops is the day the list goes blind, which is what the
live check is for.

**Every selector lives in one typed table, and the driver speaks locators.**
`SELECTORS` (`selectors.ts` / `selectors.py`) is a `Record<Vendor, VendorSelectors>`
with one row per vendor: hosts on the wire, challenge and checkbox iframes,
inline widget shapes, the response field, the accepted and checked markers,
submit controls, text inputs, slider handles and pieces. Detection, the solved
test, the fresh-round test and the banner read are each one generic pass over
that table, in table order, so a vendor is added by adding a row and the type
checker refuses a vendor with no row. Before this the same selectors were
scattered across a dozen per-vendor branches in each port, the two ports had
already diverged (Python's "widget in the DOM" test did not count the inline
vendors; Python's fresh-round test skipped the frame-hash check for reCAPTCHA),
and the vendor hint was sniffed off the iframe `src` by a second copy of the
same substrings. The vendor and frame role are now whichever row matched. The
driver queries with `locator(sel).filter({ visible: true }).all()`, every
selector of a pass at once, never `page.$()`: the visibility filter is
Playwright 1.51+, and a stale locator is resolved to a handle with a 1 s timeout
because `elementHandle()` otherwise waits the default 30 s for a widget that
has just closed, which blows the solve budget instead of reading as stale.

**The mouse path is not ours and should not be.** It was a Bezier arc with a
Fitts's-law duration, an ease-in-out velocity profile, speed-scaled jitter and
an overshoot-and-correct. Every one of those is a MODEL of what a hand does,
tuned by hand, and every one is a closed form — which is exactly what makes it
findable. A detector does not need to know our constants; it needs to know that
the path is drawn from a two-parameter family at all. `cursory` models nothing:
it searches a database of thousands of trajectories recorded from real people
for the closest match to the requested movement, morphs that recording onto the
endpoints, and re-noises it. The realism is measured rather than asserted, and
the worst case is a bad recording rather than a recognisable curve.

IT ALSO SETTLES THE DUAL-PORT PROBLEM FOR GOOD. Every other shared surface is
two implementations and a test that they agree. The mouse was one algorithm
written twice and pinned STATISTICALLY, because that is the best two
independent implementations can do: a curve written twice differs in the last
bits and then diverges over a thousand samples. `cursory-js` is a port rather
than a rewrite — both reduce to the same numpy PCG64 stream — so a seed gives
the same trajectory in both, and the parity is now pinned exactly, timings
included. Measured: seed 42 over (120, 80) -> (940, 560) is 48 identical points
in both, coordinates agreeing to about 2e-12 px (V8 and CPython rounding `exp`,
`atan2`, `sin`, `cos` differently) and timings equal outright.

WHAT IT COST, AND WHAT IT DID NOT. Move durations track the old model at the
median (193 vs 197 ms over 30 px, 681 vs 708 over 1000) with a much longer tail
— max 1354 ms against 819 — which is what real people look like and is the
thing to watch against the per-board clock. Import is ~60 ms and the first call
5 ms, against a numpy the client already loads for OpenCV, so the per-solve cost
is noise. Touch uses the same recordings at 90 Hz; a tap adds a one-pixel contact
wobble, because a motionless tap is a synthetic one.

TWO PIECES OF OUR OWN MODELLING ON TOP OF THE RECORDINGS WERE REMOVED in the
2026-09 code cut, and this reverses what an earlier entry here said. A drag used
to be redrawn until the recording did not overshoot the drop point, because a
pointer carrying a piece drags it past the notch and back (6 to 25% of raw draws
ran more than 2 px past, with a tail reaching 200 px past a 150 px move). A
swipe used to add an AR(1) contact-patch wobble at a 0.85 directness, measured
23% faster than the mouse recordings at 150 px, with cursory arcing about twice
as far as the finger model it replaced (11.4 px vs 23.7 px of bow at 150 px).
Both were our own closed forms layered on someone else's measurement, which is
the thing the mouse model was replaced for; the tap wobble stays because a
motionless tap is the one thing no digitizer produces. If drags start failing
on the drop or a vendor starts scoring swipe spectra, this is where to look
first, and the numbers above are the baseline.

THE LICENCE IS THE PART TO BE CAREFUL WITH. Both packages are
LGPL-3.0-or-later and this product is source-available proprietary. That
combination is fine, and it is fine BECAUSE they are ordinary installed
dependencies: declared in `pyproject.toml` and `package.json`, resolved by the
user's package manager, never vendored, inlined, or bundled. `tsc` leaves
`require('cursory-js')` as a runtime import rather than inlining it, and
`copy-python.mjs` copies only our own tree. Vendoring either one is the change
that would move this obligation somewhere else, so do not, and see NOTICE.

TWO PACKAGING CONSEQUENCES, both deliberate and both part of the major bump.
The Python client's `numpy` pin moves from 2.2.6 to 2.3.5, because Cursory
requires `numpy~=2.3.3` and the old pin was OURS — opencv asks only for
`numpy>=2`. That conflicts with `numba`, which arrives only under the `[serve]`
extra (vLLM self-hosting) and is never imported by the solver. And the JS client
gains its FIRST runtime dependency; it had none, which was a real property of a
package meant to be embedded, and it is worth knowing that it is gone.
