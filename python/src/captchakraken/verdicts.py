"""The vendor's own answer to each submitted round, read off the wire. Mirrored in js/src/verdicts.ts.

Every shape below was recorded against the vendor's public demo page, never inferred: a DOM done-signal can only
say "something changed", while the answer-check response says whether the round was taken. A vendor with no
readable answer (Turnstile, and the rest of the table) is judged by the DOM signals in the page driver instead.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, List, Mapping, Optional, Sequence, Tuple

from .kinds import Verdict, Vendor

# The vendors' own HTTP refusal: hCaptcha's frame words a 429 as "Your computer or network has sent too many requests".
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


class VerdictLog:
    """Every verdict the page's network carries while a solve runs.

    A page-level listener sees the vendors' cross-origin frames too. It is optional: a page object with no `on`
    records nothing, and the driver then judges every round by the DOM, as it always has.
    """

    def __init__(self, page: Any) -> None:
        self.verdicts: List[RoundVerdict] = []
        self._read = 0
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
            if endpoint_for(url) is None:
                return
            body = response.text() if status != _TOO_MANY_REQUESTS else ""
        except Exception:
            return
        verdict = read_verdict(url, status, body)
        if verdict is not None:
            self.verdicts.append(verdict)

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
