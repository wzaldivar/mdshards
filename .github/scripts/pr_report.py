#!/usr/bin/env python3
"""Render the markdown body of a PR report comment (stdlib only).

Codecov comments on every PR by itself; SonarCloud, OSV-Scanner and
ClusterFuzzLite don't, so their workflows build the comment here and post it with
`upsert_pr_comment.sh`. Each body starts with a hidden marker so the same
comment is edited on every push instead of piling up.

  pr_report.py osv <results.sarif>          OSV-Scanner findings table
  pr_report.py sonar <project-key> <pr>     SonarCloud quality-gate table
  pr_report.py fuzz <artifacts-dir> <result> <run-url>
                                            ClusterFuzzLite crashes; <result>
                                            is the fuzz job's result

Writes the body to stdout. Always exits 0 — pass/fail is the scan job's call;
this only reports.
"""

from __future__ import annotations

import json
import pathlib
import re
import sys
import urllib.parse
import urllib.request

OSV_MARKER = "<!-- mdshards:osv-scanner -->"
SONAR_MARKER = "<!-- mdshards:sonarcloud -->"
FUZZ_MARKER = "<!-- mdshards:fuzz -->"

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


_PY_EXCEPTION = "=== Uncaught Python exception: ==="
# Fuzzer output is attacker-shaped by definition: cap it before it's a comment.
_MAX_LINE = 300
_MAX_TRACE_LINES = 25
_MAX_REPRO = 600


def _clip(line: str) -> str:
    return line if len(line) <= _MAX_LINE else line[:_MAX_LINE] + " …"


def _fenced(lines: list[str]) -> list[str]:
    """A code block whose fence outruns any backtick run in the content, so
    fuzzer-chosen text can't close it and inject markdown (or @-mentions)."""
    longest = max((len(m) for line in lines for m in re.findall(r"`+", line)), default=0)
    fence = "`" * max(3, longest + 1)
    return [fence + "text", *lines, fence]


# The fuzz targets report a broken invariant as three labelled lines (see
# `_fail` in backend/fuzz/fuzz_*.py). The call carries the fuzzer's input, so
# it gets more room than an ordinary line.
_INVARIANT_LINE = re.compile(r"(called|got|expected):\s+(.*)")
_FRAME = re.compile(r'\s*File "(?P<file>[^"]+)", line (?P<line>\d+), in (?P<func>\S+)')
_MAX_CALL = 1200


def _crash(summary: pathlib.Path) -> tuple[str, list[str], str, dict[str, str]]:
    """(headline, trace lines, base64 reproducer, invariant) from a
    ClusterFuzzLite `<kind>-<hash>.summary` — the fuzzer's output for the
    crashing run. `invariant` holds called / got / expected when the target
    reported one, and is empty for any other kind of crash."""
    lines = summary.read_text(encoding="utf-8", errors="replace").splitlines()
    headline, trace = "", []
    invariant: dict[str, str] = {}
    if _PY_EXCEPTION in "\n".join(lines):
        start = next(i for i, line in enumerate(lines) if _PY_EXCEPTION in line) + 1
        for line in lines[start:]:
            if not line.strip():
                break
            trace.append(_clip(line))
            match = _INVARIANT_LINE.fullmatch(line)
            if match and match[1] not in invariant:
                value = match[2]
                invariant[match[1]] = value if len(value) <= _MAX_CALL else value[:_MAX_CALL] + " …"
        headline = trace[0] if trace else ""
        if not {"called", "got", "expected"} <= set(invariant):
            invariant = {}
        else:
            # Where in the fuzz target the check lives: the innermost frame
            # that isn't the `_fail` reporter itself.
            frames = [m for m in map(_FRAME.match, lines[start:]) if m and m["func"] != "_fail"]
            if frames and re.fullmatch(r"fuzz_\w+\.py", frames[-1]["file"]):
                invariant["check"] = (
                    f"`backend/fuzz/{frames[-1]['file']}:{frames[-1]['line']}`"
                    f" (`{frames[-1]['func']}`)"
                )
    if not headline:
        # Native crash / timeout / OOM: no Python traceback, only sanitizer output.
        start = next((i for i, line in enumerate(lines) if "ERROR:" in line), None)
        if start is not None:
            trace = [_clip(line) for line in lines[start : start + _MAX_TRACE_LINES]]
        headline = next(
            (line.strip() for line in lines if line.startswith("SUMMARY:")),
            trace[0] if trace else "crash (no summary line)",
        )
    repro = next((line[8:].strip() for line in lines if line.startswith("Base64: ")), "")
    return _clip(headline), trace[:_MAX_TRACE_LINES], repro, invariant


def fuzz(artifacts_dir: str, result: str, run_url: str) -> str:
    out = [FUZZ_MARKER, "## Fuzzing (ClusterFuzzLite)", ""]
    # crashes-<target>/<sanitizer>/<kind>-<hash>.summary
    summaries = sorted(pathlib.Path(artifacts_dir).glob("crashes-*/*/*.summary"))
    if not summaries:
        if result == "success":
            out.append(":white_check_mark: No crashes found in this run.")
        else:
            out.append(
                f":warning: The fuzz job ended as **{result}** without a crash artifact — "
                f"likely a build or infrastructure error. [See the run]({run_url})."
            )
        return "\n".join(out) + "\n"

    targets = {s.parent.parent.name.removeprefix("crashes-") for s in summaries}
    out.append(
        f":x: **{len(summaries)}** crash{'' if len(summaries) == 1 else 'es'} "
        f"in **{len(targets)}** target{'' if len(targets) == 1 else 's'} — [run]({run_url})."
    )
    for summary in summaries:
        target = summary.parent.parent.name.removeprefix("crashes-")
        unit = summary.name.removesuffix(".summary")
        headline, trace, repro, invariant = _crash(summary)
        out += ["", f"### `{target}` ({summary.parent.name})"]
        if invariant:
            # The readable form: what was called, with which value, and how
            # the result differs from what the invariant requires.
            for label, key in (("Called", "called"), ("Got", "got"), ("Expected", "expected")):
                out += ["", f"**{label}**", "", *_fenced([invariant[key]])]
            if "check" in invariant:
                out += ["", f"Checked by the fuzz target at {invariant['check']}."]
        else:
            out += ["", *_fenced([headline])]
        if len(trace) > 1:
            out += ["", "<details><summary>Trace</summary>", "", *_fenced(trace), "", "</details>"]
        out += ["", f"Reproducer `{unit}` is in the run's `crashes-{target}` artifact."]
        # Strict base64 only: this lands inside a shell snippet people paste.
        if re.fullmatch(r"[A-Za-z0-9+/]+=*", repro) and len(repro) <= _MAX_REPRO:
            out += [
                "",
                "<details><summary>Reproduce locally</summary>",
                "",
                "Build the fuzzers as in `backend/fuzz/README.md`, then:",
                "",
                "```sh",
                f"echo '{repro}' | base64 -d > {unit}",
                f"/out/{target} {unit}",
                "```",
                "",
                "</details>",
            ]
    return "\n".join(out) + "\n"


def main(argv: list[str]) -> int:
    if len(argv) == 3 and argv[1] == "osv":
        sys.stdout.write(osv(argv[2]))
    elif len(argv) == 4 and argv[1] == "sonar":
        sys.stdout.write(sonar(argv[2], argv[3]))
    elif len(argv) == 5 and argv[1] == "fuzz":
        sys.stdout.write(fuzz(argv[2], argv[3], argv[4]))
    else:
        sys.stderr.write(__doc__ or "")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
