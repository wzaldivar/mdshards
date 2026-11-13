#!/usr/bin/env python3
"""Render the markdown body of a PR report comment (stdlib only).

Codecov comments on every PR by itself; SonarCloud and OSV-Scanner don't, so
their workflows build the comment here and post it with
`upsert_pr_comment.sh`. Each body starts with a hidden marker so the same
comment is edited on every push instead of piling up.

  pr_report.py osv <results.sarif>          OSV-Scanner findings table
  pr_report.py sonar <project-key> <pr>     SonarCloud quality-gate table

Writes the body to stdout. Always exits 0 — pass/fail is the scan job's call;
this only reports.
"""

from __future__ import annotations

import json
import re
import sys
import urllib.parse
import urllib.request

OSV_MARKER = "<!-- mdshards:osv-scanner -->"
SONAR_MARKER = "<!-- mdshards:sonarcloud -->"

_OSV_MESSAGE = re.compile(
    r"Package '(?P<name>.+)@(?P<version>[^@']+)' is vulnerable to '(?P<id>[^']+)'"
)

# A table past this many rows stops being a summary; the rest is in the run.
_MAX_ROWS = 50


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ").strip()


def _source(uri: str) -> str:
    """SARIF location URI → repo-relative path (the runner's checkout prefix is noise)."""
    path = urllib.parse.unquote(urllib.parse.urlparse(uri).path or uri)
    for prefix in ("/github/workspace/", "/home/runner/work/"):
        if path.startswith(prefix):
            path = path[len(prefix) :]
            if prefix.endswith("work/"):
                # /home/runner/work/<repo>/<repo>/...
                path = path.split("/", 2)[-1]
    return path.lstrip("/")


def osv(sarif_path: str) -> str:
    with open(sarif_path, encoding="utf-8") as fh:
        run = json.load(fh)["runs"][0]
    rules = {rule["id"]: rule for rule in run["tool"]["driver"].get("rules", [])}

    rows = []
    for result in run.get("results", []):
        rule = rules.get(result.get("ruleId", ""), {})
        match = _OSV_MESSAGE.search(result["message"]["text"])
        vuln_id = match["id"] if match else result.get("ruleId", "?")
        try:
            severity = float(rule.get("properties", {}).get("security-severity", ""))
        except ValueError:
            severity = -1.0
        summary = rule.get("shortDescription", {}).get("text", "")
        locations = result.get("locations") or [{}]
        uri = locations[0].get("physicalLocation", {}).get("artifactLocation", {}).get("uri", "")
        rows.append(
            (
                severity,
                match["name"] if match else "?",
                match["version"] if match else "?",
                vuln_id,
                summary.removeprefix(f"{vuln_id}: "),
                _source(uri),
            )
        )
    # The SARIF can carry the same finding more than once (seen for pinned
    # requirements.txt entries); one row per package + advisory + source.
    rows = sorted(set(rows), key=lambda r: (-r[0], r[1], r[3]))

    out = [OSV_MARKER, "## OSV-Scanner", ""]
    if not rows:
        out.append(":white_check_mark: No known vulnerabilities in the scanned dependencies.")
        return "\n".join(out) + "\n"

    packages = {(r[1], r[2]) for r in rows}
    out += [
        f":x: **{len(rows)}** known vulnerabilit{'y' if len(rows) == 1 else 'ies'} "
        f"in **{len(packages)}** package{'' if len(packages) == 1 else 's'}.",
        "",
        "| CVSS | Package | Version | Advisory | Summary | Source |",
        "| ---: | --- | --- | --- | --- | --- |",
    ]
    for severity, name, version, vuln_id, summary, source in rows[:_MAX_ROWS]:
        cvss = f"{severity:.1f}" if severity >= 0 else "–"
        out.append(
            f"| {cvss} | `{_cell(name)}` | {_cell(version)} "
            f"| [{vuln_id}](https://osv.dev/{vuln_id}) | {_cell(summary)} | `{_cell(source)}` |"
        )
    if len(rows) > _MAX_ROWS:
        out += ["", f"…and {len(rows) - _MAX_ROWS} more — see the workflow run."]
    return "\n".join(out) + "\n"


_SONAR_METRICS = {
    "new_reliability_rating": "Reliability rating (new code)",
    "new_security_rating": "Security rating (new code)",
    "new_maintainability_rating": "Maintainability rating (new code)",
    "new_coverage": "Coverage (new code)",
    "new_duplicated_lines_density": "Duplicated lines (new code)",
    "new_security_hotspots_reviewed": "Security hotspots reviewed",
}
_RATINGS = {"1": "A", "2": "B", "3": "C", "4": "D", "5": "E"}


def _sonar_value(metric: str, value: str) -> str:
    if metric.endswith("_rating"):
        return _RATINGS.get(value.split(".")[0], value)
    if metric in ("new_coverage", "new_duplicated_lines_density", "new_security_hotspots_reviewed"):
        return f"{float(value):.1f}%"
    return value


def sonar(project_key: str, pull_request: str) -> str:
    query = urllib.parse.urlencode({"projectKey": project_key, "pullRequest": pull_request})
    dashboard = "https://sonarcloud.io/summary/new_code?" + urllib.parse.urlencode(
        {"id": project_key, "pullRequest": pull_request}
    )
    out = [SONAR_MARKER, "## SonarCloud", ""]
    try:
        with urllib.request.urlopen(  # noqa: S310 — fixed https host
            f"https://sonarcloud.io/api/qualitygates/project_status?{query}", timeout=30
        ) as resp:
            status = json.load(resp)["projectStatus"]
    except Exception as exc:  # noqa: BLE001 — a report must never fail the job
        out.append(
            f":warning: Couldn't read the quality gate ({exc}). [Open the analysis]({dashboard})."
        )
        return "\n".join(out) + "\n"

    passed = status["status"] == "OK"
    out += [
        f"{':white_check_mark:' if passed else ':x:'} "
        f"Quality gate **{'passed' if passed else 'failed'}** — [open the analysis]({dashboard}).",
        "",
        "| | Condition | Value | Required |",
        "| --- | --- | ---: | ---: |",
    ]
    for cond in status.get("conditions", []):
        metric = cond["metricKey"]
        sign = "≥" if cond["comparator"] == "LT" else "≤"
        out.append(
            f"| {':white_check_mark:' if cond['status'] == 'OK' else ':x:'} "
            f"| {_SONAR_METRICS.get(metric, metric)} "
            f"| {_sonar_value(metric, cond.get('actualValue', '–'))} "
            f"| {sign} {_sonar_value(metric, cond['errorThreshold'])} |"
        )
    return "\n".join(out) + "\n"


def main(argv: list[str]) -> int:
    if len(argv) == 3 and argv[1] == "osv":
        sys.stdout.write(osv(argv[2]))
    elif len(argv) == 4 and argv[1] == "sonar":
        sys.stdout.write(sonar(argv[2], argv[3]))
    else:
        sys.stderr.write(__doc__ or "")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
