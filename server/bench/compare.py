"""Compare `bench.run` result files as a markdown table.

    uv run python -m bench.compare bench/results/ollama-*.json bench/results/mlx-*.json \\
        [--replies bench/results/replies.md]

The first file is the baseline; other rows show the change against it.
Cold = first turn of each repeat (prompt not cached); warm = the rest,
which is what every turn after the first costs in a live session.
`--replies` writes the replies per turn side by side, for reading
quality (most useful with `--mode free` runs).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVER_DIR))

from bench.metrics import summarize  # noqa: E402

# (column, metric key, which turns, statistic, lower is better)
COLUMNS = [
    ("cold TTFT, s", "ttft_s", "cold", "median", True),
    ("warm TTFT, s", "ttft_s", "warm", "median", True),
    ("warm 1st sentence, s", "first_sentence_s", "warm", "median", True),
    ("warm 1st sentence p90, s", "first_sentence_s", "warm", "p90", True),
    ("decode, tok/s", "decode_tps", "all", "median", False),
    ("prefill (server), tok/s", "prefill_tps", "warm", "median", False),
]


def load(paths: list[Path]) -> list[dict]:
    return [json.loads(p.read_text()) for p in paths]


def turns_of(report: dict, which: str) -> list[dict]:
    turns = [t for run in report["runs"] for t in run["turns"] if not t.get("error")]
    if which == "cold":
        return [t for t in turns if t["cold"]]
    if which == "warm":
        return [t for t in turns if not t["cold"]]
    return turns


def metric(report: dict, key: str, which: str, stat: str) -> float | None:
    summary = summarize([t.get(key) for t in turns_of(report, which)])
    return None if summary is None else summary[stat]


def table(reports: list[dict]) -> str:
    headers = ["backend"] + [c[0] for c in COLUMNS] + ["peak RSS, GB", "peak system Δ, GB", "errors"]
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    base = reports[0]
    for report in reports:
        cells = [report["label"]]
        for _, key, which, stat, lower_better in COLUMNS:
            value = metric(report, key, which, stat)
            base_value = metric(base, key, which, stat)
            cells.append(_cell(value, base_value, report is base, lower_better))
        memory = report.get("memory", {})
        cells.append(_gb(memory.get("peak_rss_mb")))
        cells.append(_gb(memory.get("peak_system_delta_mb")))
        errors = sum(1 for run in report["runs"] for t in run["turns"] if t.get("error"))
        cells.append(str(errors))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _cell(value: float | None, base: float | None, is_base: bool, lower_better: bool) -> str:
    if value is None:
        return "–"
    text = f"{value:.2f}"
    if is_base or not base:
        return text
    change = (value - base) / base * 100
    better = change < 0 if lower_better else change > 0
    return f"{text} ({change:+.0f}%{' ✓' if better and abs(change) >= 5 else ''})"


def _gb(mb: float | None) -> str:
    return "–" if not mb else f"{mb / 1024:.1f}"


def conditions(reports: list[dict]) -> list[str]:
    """Flag differences that would make the comparison unfair."""
    warnings = []
    for key in ("fixture", "mode", "text_source", "params"):
        values = {json.dumps(r.get(key), sort_keys=True) for r in reports}
        if len(values) > 1:
            warnings.append(f"⚠ `{key}` differs between runs: {sorted(values)}")
    machines = {json.dumps({k: r["machine"].get(k) for k in ("chip", "memory_gb", "macos")}) for r in reports}
    if len(machines) > 1:
        warnings.append(f"⚠ different machines/OS: {sorted(machines)}")
    return warnings


def replies(reports: list[dict]) -> str:
    out = []
    first_runs = [r["runs"][0]["turns"] for r in reports if r["runs"]]
    for index in range(max(len(t) for t in first_runs)):
        out.append(f"## Turn {index}")
        for report, turns in zip(reports, first_runs):
            reply = turns[index]["reply"].strip() if index < len(turns) else ""
            out.append(f"- **{report['label']}**: {reply}")
        out.append("")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("results", type=Path, nargs="+")
    ap.add_argument("--replies", type=Path, help="also write replies side by side to this markdown file")
    args = ap.parse_args(argv)

    reports = load(args.results)
    for line in conditions(reports):
        print(line)
    print(table(reports))
    if args.replies:
        args.replies.write_text(replies(reports))
        print(f"\nreplies: {args.replies}")


if __name__ == "__main__":
    main()
