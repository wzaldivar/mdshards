"""Fuzz the external-writer reconciliation core (`app/docs.py`).

Two pieces, exercised the way `reconcile_external` chains them:

* `_three_way_merge(base, ours, theirs)` — the line-based merge. Beyond not
  crashing, it must honour the identities any 3-way merge does: one side
  unchanged → the other side wins cleanly; both sides identical → that text.
* `_apply_ghost_merge` — replays the diff as `Y.Text` splices. pycrdt indexes
  by UTF-8 byte offset, so multibyte text is where it breaks: a misaligned
  splice garbles the doc or panics the Rust layer (a BaseException, which the
  fuzzer reports as a crash). After the splice the Y.Text must equal the target.

`ours` and `theirs` are derived from `base` by line edits rather than drawn
independently, so the merge sees shared sync lines instead of three unrelated
strings that always conflict.

Run locally (Linux, from backend/):  PYTHONPATH=. python fuzz/fuzz_merge.py
"""

import sys
from pathlib import Path

import atheris

with atheris.instrument_imports():
    from pycrdt import Doc, Text

    from app.docs import TEXT_KEY, DocumentManager, _DocState

_LINE_ENDINGS = ["\n", "\r\n", "\r", "\u2028", ""]


def _line(fdp: atheris.FuzzedDataProvider) -> str:
    body = fdp.ConsumeUnicodeNoSurrogates(fdp.ConsumeIntInRange(0, 12))
    return body + fdp.PickValueInList(_LINE_ENDINGS)


def _edited(fdp: atheris.FuzzedDataProvider, base: list[str]) -> str:
    lines = list(base)
    for _ in range(fdp.ConsumeIntInRange(0, 4)):
        pos = fdp.ConsumeIntInRange(0, len(lines))
        op = fdp.ConsumeIntInRange(0, 2)
        if op == 0 or not lines:
            lines.insert(pos, _line(fdp))
        elif op == 1:
            del lines[min(pos, len(lines) - 1)]
        else:
            lines[min(pos, len(lines) - 1)] = _line(fdp)
    return "".join(lines)


def _ghost(current: str, target: str) -> None:
    doc = Doc()
    text = doc.get(TEXT_KEY, type=Text)
    if current:
        text.insert(0, current)
    state = _DocState(doc=doc, disk_path=Path("fuzz.md"))
    DocumentManager._apply_ghost_merge(state, current, target)
    if str(text) != target:
        raise AssertionError(f"ghost merge {current!r} -> {target!r} produced {str(text)!r}")


def TestOneInput(data: bytes) -> None:
    fdp = atheris.FuzzedDataProvider(data)
    base_l = [_line(fdp) for _ in range(fdp.ConsumeIntInRange(0, 8))]
    base = "".join(base_l)
    ours = _edited(fdp, base_l)
    theirs = _edited(fdp, base_l)

    merge = DocumentManager._three_way_merge
    for got, want in (
        (merge(base, ours, base), ours),
        (merge(base, base, theirs), theirs),
        (merge(base, ours, ours), ours),
    ):
        if got != (want, False):
            raise AssertionError(f"merge identity broken: base={base!r} got={got!r}")

    merged, conflict = merge(base, ours, theirs)
    # The IN path: a clean merge is spliced into the live doc holding `ours`.
    if not conflict:
        _ghost(ours, merged)
    _ghost(ours, theirs)


def main() -> None:
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
