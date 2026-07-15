#!/usr/bin/env python3
"""Validate the Docker Hub repository description artifacts before they ship.

The Docker Hub page is synced via peter-evans/dockerhub-description: an inline
`short-description` plus the overview markdown at `readme-filepath`. That lives
in the reusable dockerhub-description workflow (release.yml calls into it, so
there's a single copy). Docker Hub silently rejects/truncates a short
description over 100 chars and a full description over 25000, so a broken value
only shows up as a wrong page after a sync. This guard catches it in CI on the
PR that introduces it instead.

Checks (stdlib only, no external deps):
  1. exactly one source of the short-description; it is <= 100 chars. Any
     workflow carrying an inline `short-description:` counts as a source, so a
     re-introduced duplicate is caught...
  2. ...and if more than one source exists, they must be byte-identical (no
     drift between copies).
  3. overview file (readme-filepath) exists and is <= 25000 chars
  4. no hardcoded `X.Y.Z` version tags in the overview (they go stale — the
     "Supported tags" section must describe the scheme, not pin a version)
  5. every markdown link is absolute (http/https) or an in-page anchor;
     Docker Hub has no repo context, so relative links break

Exits non-zero on any failure.
"""

from __future__ import annotations

import pathlib
import re
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"

SHORT_MAX = 100
FULL_MAX = 25000


def main() -> int:
    failures: list[str] = []

    # Discover every workflow that carries an inline Docker Hub short-description
    # — the syncing source(s). Normally one (dockerhub-description.yml); more
    # than one means a copy was re-introduced and must be kept identical.
    shorts: dict[str, str] = {}
    readmes: dict[str, str] = {}
    for wf in sorted(WORKFLOWS.glob("*.yml")):
        text = wf.read_text()
        sm = re.search(r'short-description:\s*"([^"]*)"', text)
        if not sm:
            continue
        shorts[wf.name] = sm.group(1)
        rm = re.search(r"readme-filepath:\s*\./(\S+)", text)
        if rm:
            readmes[wf.name] = rm.group(1)

    # 1. a source exists and each is within the length limit
    if not shorts:
        failures.append("no workflow carries a short-description — nothing syncs the Docker Hub page")
    for name, short in shorts.items():
        if len(short) > SHORT_MAX:
            failures.append(f"{name}: short-description is {len(short)} chars (max {SHORT_MAX})")

    # 2. all copies identical
    if len(set(shorts.values())) > 1:
        failures.append(f"short-description differs across workflows: {shorts}")

    # 3. overview file exists and within the full-description limit
    overview = None
    if not readmes:
        failures.append("no readme-filepath found in any syncing workflow")
    elif len(set(readmes.values())) > 1:
        failures.append(f"readme-filepath differs across workflows: {readmes}")
    else:
        overview = REPO_ROOT / next(iter(readmes.values()))
        if not overview.exists():
            failures.append(f"readme-filepath does not exist: {overview}")
            overview = None

    if overview is not None:
        text = overview.read_text()
        if len(text) > FULL_MAX:
            failures.append(f"overview is {len(text)} chars (max {FULL_MAX})")

        # 4. no hardcoded semver tags (they drift — we hit this at 1.0.0 vs 1.3.2)
        stale = re.findall(r"`\d+\.\d+\.\d+`", text)
        if stale:
            failures.append(f"hardcoded version tag(s) in overview: {stale}")

        # 5. links must be absolute or in-page anchors
        bad = [
            link
            for link in re.findall(r"\]\((.*?)\)", text)
            if not (link.startswith("http") or link.startswith("#"))
        ]
        if bad:
            failures.append(f"non-absolute markdown link(s): {bad}")

    if failures:
        print("Docker Hub description validation FAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1

    src = ", ".join(sorted(shorts))
    print(f"Docker Hub description validation passed (source: {src}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
