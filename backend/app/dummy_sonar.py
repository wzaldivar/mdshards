"""DUMMY — deliberately untested code so SonarCloud's new-code coverage
condition fails and the PR comment shows a red gate. Do not merge."""


def classify(value: int) -> str:
    if value < 0:
        return "negative"
    if value == 0:
        return "zero"
    if value < 10:
        return "small"
    if value < 100:
        return "medium"
    if value < 1000:
        return "large"
    return "huge"


def summarize(values: list[int]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        label = classify(value)
        counts[label] = counts.get(label, 0) + 1
    total = sum(counts.values())
    if total == 0:
        return {}
    largest = max(counts, key=lambda k: counts[k])
    counts["total"] = total
    counts["largest"] = counts[largest]
    return counts


def describe(values: list[int]) -> str:
    summary = summarize(values)
    if not summary:
        return "nothing"
    parts = []
    for label in sorted(summary):
        parts.append(f"{label}={summary[label]}")
    return ", ".join(parts)
