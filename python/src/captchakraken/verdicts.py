"""The vendor's own answer to each submitted round, read off the wire. Mirrored in js/src/verdicts.ts.

Every shape below was recorded against the vendor's public demo page, never inferred: a DOM done-signal can only
say "something changed", while the answer-check response says whether the round was taken. A vendor with no
readable answer (Turnstile, and the rest of the table) is judged by the DOM signals in the page driver instead.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from .kinds import Verdict, Vendor

# The vendors' own HTTP refusal: hCaptcha's frame words a 429 as "Your computer or network has sent too many requests".
_SCRIPTED_REQUESTS = ("xhr", "fetch", "script")
_TOO_MANY_REQUESTS = 429


@dataclass(frozen=True)
class RoundVerdict:
    vendor: Vendor
    verdict: Verdict


def _json(body: str) -> Any:
    try:
        return json.loads(body)
    except ValueError:
        return None


def _pass_field(body: str) -> Optional[Verdict]:
    """A JSON object whose boolean `pass` is the verdict."""
    data = _json(body)
    passed = data.get("pass") if isinstance(data, dict) else None
    return None if not isinstance(passed, bool) else Verdict.ACCEPTED if passed else Verdict.REJECTED


def _xssi_array(body: str) -> Optional[List[Any]]:
    """A JSON array behind the `)]}'` anti-hijacking line."""
    data = _json(body.split("\n", 1)[1] if body.startswith(")]}'") and "\n" in body else body)
    return data if isinstance(data, list) and data else None


def _user_verify(body: str) -> Optional[Verdict]:
    """`["uvresp", token, 1, lifetime, ...]` when taken; `["uvresp", context, 0, ..., ["rresp", ...next board]]` when refused."""
    data = _xssi_array(body)
    if data is None or data[0] != "uvresp" or len(data) < 3:
        return None
    return {1: Verdict.ACCEPTED, 0: Verdict.REJECTED}.get(data[2]) if type(data[2]) is int else None


def _new_board(body: str) -> Optional[Verdict]:
    data = _xssi_array(body)
    return Verdict.NEW_CHALLENGE if data is not None and data[0] == "rresp" else None


def _jsonp_result(body: str) -> Optional[Verdict]:
    """`callback({...})` whose `data.result` is the verdict."""
    start, end = body.find("("), body.rfind(")")
    data = _json(body[start + 1:end]) if 0 <= start < end else None
    result = (data.get("data") or {}).get("result") if isinstance(data, dict) and data.get("status") == "success" else None
    return {"success": Verdict.ACCEPTED, "fail": Verdict.REJECTED}.get(result) if isinstance(result, str) else None


def _tencent_ticket(body: str) -> Optional[Verdict]:
    """`{"errorCode": "0", "ticket": ...}` when taken; `{"errorCode": "50", "ticket": ""}` when a wrong slide is refused.
    Any other code (rate limits, expired sessions) has not been recorded, so the DOM judges it."""
    data = _json(body)
    if not isinstance(data, dict):
        return None
    code = str(data.get("errorCode"))
    if code == "0" and data.get("ticket"):
        return Verdict.ACCEPTED
    return Verdict.REJECTED if code == "50" and not data.get("ticket") else None


def _yidun_check(body: str) -> Optional[Verdict]:
    """`callback({"data": {"result": true, ...}, "error": 0})` when taken, `"result": false` with `"error": 0` when refused."""
    start, end = body.find("("), body.rfind(")")
    data = _json(body[start + 1:end]) if 0 <= start < end else None
    if not isinstance(data, dict) or data.get("error") != 0:
        return None
    result = (data.get("data") or {}).get("result")
    return {True: Verdict.ACCEPTED, False: Verdict.REJECTED}.get(result) if isinstance(result, bool) else None


def _arkose_answer(body: str) -> Optional[Verdict]:
    """`solved: true` when taken; `solved: false` with `time_end` set when the session ended refused."""
    data = _json(body)
    if not isinstance(data, dict):
        return None
    if data.get("solved") is True:
        return Verdict.ACCEPTED
    return Verdict.REJECTED if data.get("solved") is False and data.get("time_end") is not None else None


def _url_only(_body: str) -> Optional[Verdict]:
    return Verdict.NEW_CHALLENGE


@dataclass(frozen=True)
class VerdictEndpoint:
    # A URL substring naming the vendor's own endpoint.
    marker: str
    read: Callable[[str], Optional[Verdict]]


# Only a vendor listed here has a readable answer; the rest are judged by the DOM done-signals.
VERDICT_ENDPOINTS: Mapping[Vendor, Sequence[VerdictEndpoint]] = {
    # The deal endpoint's body is encrypted, so its URL is the whole signal.
    Vendor.HCAPTCHA: (VerdictEndpoint("hcaptcha.com/checkcaptcha/", _pass_field),
                      VerdictEndpoint("hcaptcha.com/getcaptcha/", _url_only)),
    Vendor.RECAPTCHA: (VerdictEndpoint("/recaptcha/api2/userverify", _user_verify),
                       VerdictEndpoint("/recaptcha/api2/reload", _new_board)),
    Vendor.GEETEST: (VerdictEndpoint("geetest.com/verify", _jsonp_result),
                     VerdictEndpoint("geetest.com/load", _url_only)),
    Vendor.TENCENT: (VerdictEndpoint("/cap_union_new_verify", _tencent_ticket),),
    Vendor.YIDUN: (VerdictEndpoint("dun.163.com/api/v3/check", _yidun_check),),
    # Sites serve this from their own hostnames, so the path is what identifies it.
    Vendor.FUNCAPTCHA: (VerdictEndpoint("/fc/ca/", _arkose_answer),),
}


def endpoint_for(url: str) -> Optional[Tuple[Vendor, VerdictEndpoint]]:
    """(vendor, endpoint) whose marker the URL carries, so a listener reads only the bodies it can judge."""
    return next(((vendor, e) for vendor, endpoints in VERDICT_ENDPOINTS.items() for e in endpoints
                 if e.marker in url), None)


def read_verdict(url: str, status: int, body: str) -> Optional[RoundVerdict]:
    found = endpoint_for(url)
    if found is None:
        return None
    vendor, endpoint = found
    if status == _TOO_MANY_REQUESTS:
        return RoundVerdict(vendor, Verdict.BLOCKED)
    verdict = endpoint.read(body) if 200 <= status < 300 else None
    return RoundVerdict(vendor, verdict) if verdict is not None else None


# ── whether a board moves, read off the file it is dealt as ─────────────────
# Measured 2026-11-14 on the live demos. hCaptcha (46 deals over three sitekeys) loads each board from
# imgs*.hcaptcha.com/tip/: image/jpeg for every still deal, video/webm for every animated one. GeeTest v4's /load names
# its challenge in plain JSONP, and only the two svg types moved (22 deals over seven demo pages). A vendor, file or
# type not listed here gives no hint, and the driver films the board to find out, as it always has.
_GEETEST_MOVING = frozenset({"svg_icon", "svg_seed"})
_GEETEST_STILL = frozenset({"slide", "icon", "nine", "match", "winlinze"})


def _media_moves(content_type: str, _body: str) -> Optional[bool]:
    # A GIF may move, so it says nothing either way; every still hCaptcha board measured was a jpeg or a png.
    kind = content_type.split(";", 1)[0].strip().lower()
    if kind == "image/gif":
        return None
    return {"video": True, "image": False}.get(kind.split("/", 1)[0])


def _cybersiara_board_moves(_content_type: str, body: str) -> Optional[bool]:
    # GenerateCaptcha names the board's file in HtmlFormate; every one measured (4 deals) was a GIF that moved.
    data = _json(body)
    board = data.get("HtmlFormate") if isinstance(data, dict) else None
    return True if isinstance(board, str) and board.lower().split("?", 1)[0].endswith(".gif") else None


def _geetest_type_moves(_content_type: str, body: str) -> Optional[bool]:
    start, end = body.find("("), body.rfind(")")
    data = _json(body[start + 1:end]) if 0 <= start < end else None
    kind = (data.get("data") or {}).get("captcha_type") if isinstance(data, dict) else None
    return True if kind in _GEETEST_MOVING else False if kind in _GEETEST_STILL else None


@dataclass(frozen=True)
class MotionSignal:
    # A URL substring naming the response that carries the board, or names its kind.
    marker: str
    read: Callable[[str, str], Optional[bool]]
    needs_body: bool


MOTION_SIGNALS: Mapping[Vendor, Sequence[MotionSignal]] = {
    Vendor.HCAPTCHA: (MotionSignal("hcaptcha.com/tip/", _media_moves, needs_body=False),),
    Vendor.GEETEST: (MotionSignal("geetest.com/load", _geetest_type_moves, needs_body=True),),
    Vendor.CYBERSIARA: (MotionSignal("mycybersiara.com/api/GenerateCaptcha", _cybersiara_board_moves,
                                     needs_body=True),),
}


# ── the same, read back from a frame's performance timeline ──────────────────
# The listener hears only what loads after solve() starts. A widget the caller opened first, or a board the browser
# served from its cache, was dealt before then, and each frame's resource timeline still lists what it loaded and what
# loaded it. Only entries after the vendor's latest deal count, and a full buffer (where new entries are dropped and the
# latest deal may be missing) says nothing. Measured 2026-11-14: GeeTest's board files sit under
# static.geetest.com/captcha_v4/policy/<id>/<captcha_type>/, hCaptcha's under /tip/ loaded by an img, CyberSiara's as
# a GIF under embed.mycybersiara.com/CyberSiara/.
TIMELINE_JS = """() => {
  const all = performance.getEntriesByType('resource');
  return {full: all.length >= 250, entries: all.map(e => [e.initiatorType, e.name])};
}"""


def _hcaptcha_tip_moves(initiator: str, _url: str) -> Optional[bool]:
    return True if initiator in ("video", "audio", "source") else False if initiator == "img" else None


def _geetest_path_moves(_initiator: str, url: str) -> Optional[bool]:
    parts = url.split("captcha_v4/policy/", 1)[-1].split("/")
    kind = parts[1] if len(parts) > 1 else None
    return True if kind in _GEETEST_MOVING else False if kind in _GEETEST_STILL else None


def _cybersiara_file_moves(_initiator: str, url: str) -> Optional[bool]:
    return True if url.lower().split("?", 1)[0].endswith(".gif") else None


@dataclass(frozen=True)
class TimelineBoard:
    deal: str
    board: str
    read: Callable[[str, str], Optional[bool]]


TIMELINE_BOARDS: Mapping[Vendor, TimelineBoard] = {
    Vendor.HCAPTCHA: TimelineBoard("hcaptcha.com/getcaptcha/", "hcaptcha.com/tip/", _hcaptcha_tip_moves),
    Vendor.GEETEST: TimelineBoard("geetest.com/load", "static.geetest.com/captcha_v4/policy/", _geetest_path_moves),
    Vendor.CYBERSIARA: TimelineBoard("mycybersiara.com/api/GenerateCaptcha", "mycybersiara.com/CyberSiara/",
                                     _cybersiara_file_moves),
}


def motion_from_timeline(vendor: Vendor, timeline: Any) -> Optional[bool]:
    """What one frame's resource timeline says about the vendor's latest board, or None."""
    spec = TIMELINE_BOARDS.get(vendor)
    if spec is None or not isinstance(timeline, dict) or timeline.get("full"):
        return None
    entries = [e for e in timeline.get("entries") or () if isinstance(e, (list, tuple)) and len(e) == 2]
    last_deal = max((i for i, (_kind, url) in enumerate(entries) if spec.deal in str(url)), default=None)
    if last_deal is None:
        return None
    reads = [spec.read(str(kind), str(url)) for kind, url in entries[last_deal + 1:] if spec.board in str(url)]
    return True if True in reads else False if False in reads else None


def motion_signal_for(url: str) -> Optional[Tuple[Vendor, MotionSignal]]:
    return next(((vendor, s) for vendor, signals in MOTION_SIGNALS.items() for s in signals if s.marker in url), None)


def _deals_a_board(url: str) -> Optional[Vendor]:
    """The vendor whose deal endpoint this is: what it said about the last board no longer holds."""
    found = endpoint_for(url)
    return found[0] if found is not None and found[1].read is _url_only else None


def _is_a_scripted_request(response: Any) -> bool:
    try:
        return response.request.resource_type in _SCRIPTED_REQUESTS
    except Exception:
        return False


class VerdictLog:
    """Every verdict the page's network carries while a solve runs.

    A page-level listener sees the vendors' cross-origin frames too. It is optional: a page object with no `on`
    records nothing, and the driver then judges every round by the DOM, as it always has.
    """

    def __init__(self, page: Any) -> None:
        self.verdicts: List[RoundVerdict] = []
        #: Requests the page's scripts have made. A board that answers a press with none has refused nothing.
        self.exchanges = 0
        self._read = 0
        #: What each vendor's network said about its current board: True moves, False is still.
        self._motion: Dict[Vendor, bool] = {}
        self._deals: Dict[Vendor, int] = {}
        self._page = page
        self._attached = False
        try:
            page.on("response", self._on_response)
            self._attached = True
        except Exception:
            pass

    def _on_response(self, response: Any) -> None:
        try:
            url, status = response.url, response.status
            if _is_a_scripted_request(response):
                self.exchanges += 1
            dealt = _deals_a_board(url)
            if dealt is not None:
                # Before the body is read: the new board's own file can arrive while it is.
                self._motion.pop(dealt, None)
                self._deals[dealt] = self._deals.get(dealt, 0) + 1
            signal = motion_signal_for(url)
            # A body read for an earlier deal must not describe a board that has since been replaced.
            deal = self._deals.get(signal[0], 0) if signal is not None else 0
            if endpoint_for(url) is None and signal is None:
                return
            # Decoded leniently, as a browser's text() is: one deal endpoint answers in ciphertext, and its URL alone
            # is the signal.
            needs_body = endpoint_for(url) is not None or (signal is not None and signal[1].needs_body)
            body = response.body().decode("utf-8", "replace") if needs_body and status != _TOO_MANY_REQUESTS else ""
            content_type = (response.headers or {}).get("content-type", "") if signal is not None else ""
        except Exception:
            return
        if signal is not None and 200 <= status < 300 and self._deals.get(signal[0], 0) == deal:
            self._note_motion(signal[0], signal[1].read(content_type, body))
        verdict = read_verdict(url, status, body)
        if verdict is not None:
            self.verdicts.append(verdict)

    def _note_motion(self, vendor: Vendor, moves: Optional[bool]) -> None:
        # One moving file makes the board a moving one: a board may also load a still example.
        if moves is not None and not self._motion.get(vendor):
            self._motion[vendor] = moves

    def board_motion(self, vendor: Vendor) -> Optional[bool]:
        """Whether the vendor dealt its current board as a moving one; None when neither its network nor a frame's
        timeline has said."""
        heard = self._motion.get(vendor)
        if heard is not None or vendor not in TIMELINE_BOARDS:
            return heard
        try:
            frames = list(self._page.frames)
        except Exception:
            return None
        reads = []
        for frame in frames:
            try:
                reads.append(motion_from_timeline(vendor, frame.evaluate(TIMELINE_JS)))
            except Exception:
                continue
        return True if True in reads else False if False in reads else None

    @property
    def listening(self) -> bool:
        return self._attached

    def fresh(self) -> List[RoundVerdict]:
        """The verdicts that arrived since the last call."""
        new, self._read = self.verdicts[self._read:], len(self.verdicts)
        return new

    def decisive(self) -> Optional[Verdict]:
        """The last accept or reject, which is what the round came to."""
        return next((v.verdict for v in reversed(self.verdicts)
                     if v.verdict in (Verdict.ACCEPTED, Verdict.REJECTED)), None)

    def close(self) -> None:
        if self._attached:
            try:
                self._page.remove_listener("response", self._on_response)
            except Exception:
                pass
