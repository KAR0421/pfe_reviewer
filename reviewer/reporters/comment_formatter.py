"""Markdown comment formatter for Bitbucket PR comments.

Given the JSON dict produced by ``json_reporter.to_json_dict``, render
a short Markdown string suitable for posting as a single PR comment.
The format is informal (not a stable contract); only the
``json_reporter`` schema is contractual.

Layout:

```
## 🤖 REVIEWER — Static Analysis Report

**Summary:** {E} errors • {W} warnings • {I} info

[ ✅ No issues found.      <- when total == 0 ]
[ ### Top issues          <- otherwise ]
[ {emoji} **{rule_id}** at `{bizrule}:{line}` — {message} ]
[ ... up to 3 bullets ... ]

📄 [View full report]({url}) — {total} finding(s) across {N} categor(y|ies)
```

Severity emoji:  error → 🔴, warning → 🟡, info → 🔵, other → ⚪.

The "top issues" section picks up to 3 findings by severity priority
(error > warning > info) and, within a severity, by source order
(pack order → bizrule order → ``(line, rule_id)`` order already
applied by the JSON reporter). Fewer than 3 findings means a partial
section; zero findings means no section at all.

Messages are flattened (newlines stripped, whitespace collapsed) and
truncated to 200 characters (197 + ``...``) so a single finding can't
blow out the comment.
"""
from __future__ import annotations

import re


__all__ = ["format_comment", "REPORT_URL_PLACEHOLDER"]


REPORT_URL_PLACEHOLDER = "REPORT_URL_PLACEHOLDER"

_SEVERITY_EMOJI = {
    "error": "🔴",
    "warning": "🟡",
    "info": "🔵",
}
_UNKNOWN_EMOJI = "⚪"

_MAX_MESSAGE = 200
_SEVERITY_ORDER = ("error", "warning", "info")


def format_comment(
    report_data: dict,
    *,
    report_url: str | None = None,
) -> str:
    """Render ``report_data`` (the dict from ``to_json_dict``) as a
    Markdown PR comment. See module docstring for the layout.
    """
    summary = report_data.get("summary", {})
    by_sev = summary.get("by_severity", {})
    errors = by_sev.get("error", 0)
    warnings = by_sev.get("warning", 0)
    infos = by_sev.get("info", 0)
    total = summary.get("total", 0)
    by_cat = summary.get("by_category", {})
    category_count = len(by_cat)

    lines: list[str] = []
    lines.append("## 🤖 REVIEWER — Static Analysis Report")
    lines.append("")
    lines.append(
        f"**Summary:** {errors} errors • {warnings} warnings • "
        f"{infos} info"
    )
    lines.append("")

    if total == 0:
        lines.append("✅ No issues found.")
    else:
        flat = list(_flatten(report_data))
        top = _pick_top(flat, limit=3)
        lines.append("### Top issues")
        lines.append("")
        for f in top:
            lines.append(_render_bullet(f))
        lines.append("")

    url = report_url if report_url is not None else REPORT_URL_PLACEHOLDER
    finding_word = "finding" if total == 1 else "findings"
    category_word = "category" if category_count == 1 else "categories"
    lines.append(
        f"📄 [View full report]({url}) — {total} {finding_word} "
        f"across {category_count} {category_word}"
    )

    return "\n".join(lines)


def _flatten(report_data: dict):
    """Yield ``(severity, rule_id, line, bizrule_name, message)`` for
    every finding in source order (pack → bizrule → finding).
    """
    for pack in report_data.get("packs", []):
        for br in pack.get("bizrules", []):
            name = br.get("name", "?")
            for f in br.get("findings", []):
                yield (
                    f.get("severity", ""),
                    f.get("rule_id", ""),
                    f.get("line", 0),
                    name,
                    f.get("message", ""),
                )


def _pick_top(flat: list, *, limit: int) -> list:
    """Pick up to ``limit`` findings: errors first, then warnings,
    then info, then anything unknown. Source order within a severity.
    """
    buckets: dict[str, list] = {sev: [] for sev in _SEVERITY_ORDER}
    other: list = []
    for item in flat:
        sev = item[0]
        if sev in buckets:
            buckets[sev].append(item)
        else:
            other.append(item)
    picked: list = []
    for sev in _SEVERITY_ORDER:
        for item in buckets[sev]:
            if len(picked) >= limit:
                return picked
            picked.append(item)
    for item in other:
        if len(picked) >= limit:
            return picked
        picked.append(item)
    return picked


def _render_bullet(finding: tuple) -> str:
    sev, rule_id, line, bizrule, message = finding
    emoji = _SEVERITY_EMOJI.get(sev, _UNKNOWN_EMOJI)
    msg = _clean_message(message)
    return f"{emoji} **{rule_id}** at `{bizrule}:{line}` — {msg}"


def _clean_message(msg: str) -> str:
    """Strip newlines, collapse whitespace, truncate to 200 chars."""
    flat = re.sub(r"\s+", " ", msg).strip()
    if len(flat) > _MAX_MESSAGE:
        return flat[: _MAX_MESSAGE - 3] + "..."
    return flat
