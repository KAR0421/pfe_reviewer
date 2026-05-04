"""Console reporter — pretty-prints a Report for humans."""
from __future__ import annotations

from ..engine.finding import Report


def print_report(report: Report, *, label: str = "") -> None:
    """Print a Report to stdout. ``label`` distinguishes parallel runs."""
    prefix = f"[{label}] " if label else ""
    if not report.findings:
        print(f"{prefix}{report.rule_name}: no issues found.")
        return
    print(f"{prefix}{report.rule_name}: {len(report.findings)} finding(s)")
    for i, f in enumerate(report.findings, 1):
        loc = f"line {f.line}" if f.line is not None else "—"
        print(
            f"  {i}. [{f.rule_id} {f.severity}] {loc}: {f.message}"
        )
