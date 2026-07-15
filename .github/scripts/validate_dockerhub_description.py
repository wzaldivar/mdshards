#!/usr/bin/env python3
"""Validate the Docker Hub repository description artifacts before they ship.

Two workflows sync the Docker Hub page via peter-evans/dockerhub-description:
release.yml (at publish time) and dockerhub-description.yml (manual, out of
band). Each carries an inline `short-description` plus the overview markdown at
`readme-filepath`. Docker Hub silently rejects/truncates a short description
over 100 chars and a full description over 25000, so a broken value only shows
up as a wrong page after a sync. This guard catches it in CI on the PR that
introduces it instead.

Checks (stdlib only, no external deps):
  1. short-description present and <= 100 chars in every syncing workflow
  2. the short-description is identical across those workflows (they each need
     their own inline copy — this keeps the copies from drifting)
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
# Every workflow that syncs the Docker Hub description carries its own inline
# short-description; check 2 keeps them identical.
SYNC_WORKFLOWS = ["release.yml", "dockerhub-description.yml"]
RELEASE_YML = WORKFLOWS / "release.yml"

SHORT_MAX = 100
FULL_MAX = 25000


def main() -> int:
    release = RELEASE_YML.read_text()

    readme_m = re.search(r"readme-filepath:\s*\./(\S+)", release)

    failures: list[str] = []

    # 1. short description present and within limit in every syncing workflow
    shorts: dict[str, str] = {}
    for name in SYNC_WORKFLOWS:
        path = WORKFLOWS / name
        if not path.exists():
            failures.append(f"syncing workflow missing: {name}")
            continue
        m = re.search(r'short-description:\s*"([^"]*)"', path.read_text())
        if not m:
            failures.append(f"no short-description found in {name}")
            continue
        shorts[name] = m.group(1)
        if len(m.group(1)) > SHORT_MAX:
            failures.append(f"{name}: short-description is {len(m.group(1))} chars (max {SHORT_MAX})")

    # 2. short-description identical across the syncing workflows
    if len(set(shorts.values())) > 1:
        failures.append(f"short-description differs across workflows: {shorts}")

    # 3. overview file exists and within the full-description limit
    if not readme_m:
        failures.append("no readme-filepath found in release.yml")
        overview = None
    else:
        overview = REPO_ROOT / readme_m.group(1)
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

    print("Docker Hub description validation passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
