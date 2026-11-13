"""Fuzz the origin boundary (`app/security.py`).

Header bytes are attacker-controlled, so the guard's predicates must never
raise (an exception in the outermost middleware is a 500, not a rejection)
and must keep the rules that don't depend on parsing details:

* an explicit cross-site `Sec-Fetch-Site` is always rejected;
* the `/api` gate rejects a request carrying none of `Sec-Fetch-Site`,
  `Origin`, `Referer` (bare curl);
* a request whose `Origin` matches its own `Host` passes the `/api` gate
  unless `Sec-Fetch-Site` says otherwise.

Run locally (Linux, from backend/):  PYTHONPATH=. python fuzz/fuzz_origin_guard.py
"""

import re
import sys

import atheris

with atheris.instrument_imports():
    from app.security import (
        SAFE_SEC_FETCH_SITE,
        _header,
        _is_api_or_ws,
        _route_path,
        api_request_allowed,
        is_request_allowed,
    )

_NAMES = [b"host", b"origin", b"referer", b"sec-fetch-site", b"Origin", b"HOST", b"x-other"]
_SITES = [b"same-origin", b"same-site", b"none", b"cross-site", b""]
# Hosts simple enough that urlparse round-trips them; junk Host values are
# only checked for "never raises", not for the same-origin rule.
_PLAIN_HOST = re.compile(r"[A-Za-z0-9.-]+(:[0-9]+)?")
_PATHS = ["/_mdshards/api/tree", "/_mdshards/ws/x", "/_mdshards/api", "/wiki/_mdshards/api/x", "/"]


def _fail(called: str, got: str, expected: str) -> None:
    """Report a broken invariant as call / got / expected. The three labelled
    lines are what `.github/scripts/pr_report.py` lifts into the PR comment,
    so a crash reads like a failed assertion instead of a wall of bytes."""
    raise AssertionError(
        f"fuzz invariant violated\ncalled:   {called}\ngot:      {got}\nexpected: {expected}"
    )


def _value(fdp: atheris.FuzzedDataProvider, name: bytes) -> bytes:
    if name.lower() == b"sec-fetch-site" and fdp.ConsumeBool():
        return fdp.PickValueInList(_SITES)
    return fdp.ConsumeBytes(fdp.ConsumeIntInRange(0, 64))


def TestOneInput(data: bytes) -> None:
    fdp = atheris.FuzzedDataProvider(data)
    headers = []
    for _ in range(fdp.ConsumeIntInRange(0, 6)):
        name = fdp.PickValueInList(_NAMES)
        headers.append((name, _value(fdp, name)))
    if fdp.ConsumeBool():
        path = fdp.PickValueInList(_PATHS)
    else:
        path = fdp.ConsumeUnicodeNoSurrogates(32)
    scope = {
        "type": "http",
        "path": path,
        "root_path": fdp.PickValueInList(["", "/wiki"]),
        "headers": headers,
    }

    request = f"path={path!r}, root_path={scope['root_path']!r}, headers={headers!r}"
    try:
        _is_api_or_ws(_route_path(scope))
        allowed = is_request_allowed(scope)
        api_allowed = api_request_allowed(scope)
    except Exception as exc:  # noqa: BLE001 — the guard must never raise
        _fail(
            f"the origin guard's predicates on a request with {request}",
            f"raised {type(exc).__name__}: {exc}",
            "True or False (an exception in the outermost middleware is a 500)",
        )

    site = _header(headers, b"sec-fetch-site")
    origin = _header(headers, b"origin")
    referer = _header(headers, b"referer")
    host = _header(headers, b"host")
    if site is not None and site not in SAFE_SEC_FETCH_SITE and (allowed or api_allowed):
        _fail(
            f"{'is_request_allowed' if allowed else 'api_request_allowed'}({request})",
            "returned True",
            f"False (Sec-Fetch-Site {site!r} is cross-site, always rejected)",
        )
    if site is None and origin is None and referer is None and api_allowed:
        _fail(
            f"api_request_allowed({request})",
            "returned True",
            "False (no Sec-Fetch-Site, Origin or Referer: not a browser request)",
        )
    if (
        site is None
        and host
        and _PLAIN_HOST.fullmatch(host)
        and origin is not None
        and origin.lower() in (f"http://{host}".lower(), f"https://{host}".lower())
        and not api_allowed
    ):
        _fail(
            f"api_request_allowed({request})",
            "returned False",
            f"True (Origin {origin!r} matches Host {host!r})",
        )


def main() -> None:
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
