"""Tests for the Markdown PR comment formatter."""
from __future__ import annotations

from reviewer.reporters.comment_formatter import (
    REPORT_URL_PLACEHOLDER,
    format_comment,
)


def _finding(rule_id: str, severity: str, line: int, message: str,
             category: str = "logic") -> dict:
    return {
        "rule_id": rule_id,
        "category": category,
        "severity": severity,
        "line": line,
        "message": message,
    }


def _bizrule(name: str, findings: list[dict]) -> dict:
    return {"name": name, "finding_count": len(findings), "findings": findings}


def _report(
    *,
    findings_per_bizrule: list[tuple[str, list[dict]]],
    pack_file: str = "p.pack.xml",
) -> dict:
    """Build a JSON dict matching json_reporter.to_json_dict's shape."""
    by_sev = {"error": 0, "warning": 0, "info": 0}
    by_cat: dict[str, int] = {}
    total = 0
    bizrules = []
    for name, findings in findings_per_bizrule:
        bizrules.append(_bizrule(name, findings))
        for f in findings:
            total += 1
            by_sev[f["severity"]] = by_sev.get(f["severity"], 0) + 1
            by_cat[f["category"]] = by_cat.get(f["category"], 0) + 1
    return {
        "metadata": {
            "tool": "REVIEWER",
            "version": "1.0.0",
            "timestamp": "2026-05-23T00:00:00Z",
            "directory": "/x",
        },
        "summary": {
            "total": total,
            "by_severity": by_sev,
            "by_category": by_cat,
            "pack_count": 1,
            "bizrule_count": len(bizrules),
        },
        "packs": [{"pack_file": pack_file, "bizrules": bizrules}],
    }


def test_empty_report_shows_no_issues_message() -> None:
    out = format_comment(_report(findings_per_bizrule=[]))
    assert "## 🤖 REVIEWER — Static Analysis Report" in out
    assert "**Summary:** 0 errors • 0 warnings • 0 info" in out
    assert "✅ No issues found." in out
    assert "### Top issues" not in out
    assert "0 findings across 0 categories" in out


def test_top_3_when_more_than_3_errors() -> None:
    findings = [
        _finding("SR001", "error", 1, "first"),
        _finding("SR002", "error", 2, "second"),
        _finding("SR003", "error", 3, "third"),
        _finding("SR004", "error", 4, "fourth"),
        _finding("SR005", "error", 5, "fifth"),
    ]
    out = format_comment(_report(findings_per_bizrule=[("X", findings)]))
    assert "**SR001**" in out
    assert "**SR002**" in out
    assert "**SR003**" in out
    assert "**SR004**" not in out
    assert "**SR005**" not in out


def test_top_3_mixes_severities_when_few_errors() -> None:
    findings = [
        _finding("SR001", "error", 1, "err"),
        _finding("SR010", "warning", 2, "w1"),
        _finding("SR011", "warning", 3, "w2"),
        _finding("SR012", "warning", 4, "w3"),
        _finding("SR013", "warning", 5, "w4"),
        _finding("SR014", "warning", 6, "w5"),
    ]
    out = format_comment(_report(findings_per_bizrule=[("X", findings)]))
    assert "**SR001**" in out
    assert "**SR010**" in out
    assert "**SR011**" in out
    assert "**SR012**" not in out


def test_top_3_falls_back_to_warnings_when_no_errors() -> None:
    findings = [
        _finding("SR010", "warning", 1, "w1"),
        _finding("SR011", "warning", 2, "w2"),
        _finding("SR012", "warning", 3, "w3"),
        _finding("SR013", "warning", 4, "w4"),
        _finding("SR014", "warning", 5, "w5"),
        _finding("SR090", "info", 6, "i1"),
        _finding("SR091", "info", 7, "i2"),
    ]
    out = format_comment(_report(findings_per_bizrule=[("X", findings)]))
    assert "**SR010**" in out
    assert "**SR011**" in out
    assert "**SR012**" in out
    assert "**SR013**" not in out
    assert "**SR090**" not in out


def test_top_3_falls_back_to_info_when_no_errors_or_warnings() -> None:
    findings = [_finding(f"SR09{i}", "info", i, f"i{i}") for i in range(5)]
    out = format_comment(_report(findings_per_bizrule=[("X", findings)]))
    assert "**SR090**" in out
    assert "**SR091**" in out
    assert "**SR092**" in out
    assert "**SR093**" not in out


def test_partial_section_when_total_below_3() -> None:
    findings = [_finding("SR001", "error", 1, "lonely")]
    out = format_comment(_report(findings_per_bizrule=[("X", findings)]))
    assert "### Top issues" in out
    assert "**SR001**" in out
    # Singular phrasing.
    assert "1 finding across" in out
    # Only one bullet line — count emoji occurrences.
    assert out.count("🔴") == 1


def test_severity_emojis_correct() -> None:
    findings = [
        _finding("SR001", "error", 1, "e"),
        _finding("SR010", "warning", 2, "w"),
        _finding("SR090", "info", 3, "i"),
    ]
    out = format_comment(_report(findings_per_bizrule=[("X", findings)]))
    assert "🔴 **SR001**" in out
    assert "🟡 **SR010**" in out
    assert "🔵 **SR090**" in out


def test_message_truncation_at_200_chars() -> None:
    long_msg = "x" * 250
    findings = [_finding("SR001", "error", 1, long_msg)]
    out = format_comment(_report(findings_per_bizrule=[("X", findings)]))
    # Extract the bullet line.
    line = next(ln for ln in out.splitlines() if "**SR001**" in ln)
    # Pull the message after the em-dash separator.
    msg = line.split("— ", 1)[1]
    assert len(msg) == 200
    assert msg.endswith("...")
    assert msg.startswith("x" * 10)


def test_message_newlines_stripped() -> None:
    findings = [_finding("SR001", "error", 1, "line1\nline2\n\tline3")]
    out = format_comment(_report(findings_per_bizrule=[("X", findings)]))
    line = next(ln for ln in out.splitlines() if "**SR001**" in ln)
    assert "\n" not in line.split("— ", 1)[1]
    assert "line1 line2 line3" in line


def test_report_url_substituted_when_provided() -> None:
    out = format_comment(
        _report(findings_per_bizrule=[]), report_url="https://ci/report/42"
    )
    assert "(https://ci/report/42)" in out
    assert REPORT_URL_PLACEHOLDER not in out


def test_report_url_placeholder_preserved_when_none() -> None:
    out = format_comment(_report(findings_per_bizrule=[]))
    assert f"({REPORT_URL_PLACEHOLDER})" in out


def test_singular_finding_phrasing() -> None:
    out = format_comment(
        _report(findings_per_bizrule=[
            ("X", [_finding("SR001", "error", 1, "x")])
        ])
    )
    assert "1 finding across" in out
    assert "1 findings" not in out


def test_singular_category_phrasing() -> None:
    out = format_comment(
        _report(findings_per_bizrule=[
            ("X", [_finding("SR001", "error", 1, "x", category="logic")])
        ])
    )
    assert "1 category" in out
    assert "1 categories" not in out


def test_french_message_renders_correctly() -> None:
    msg = "Règle non conforme — caractère é à l'écran"
    findings = [_finding("SR001", "error", 1, msg)]
    out = format_comment(_report(findings_per_bizrule=[("X", findings)]))
    assert msg in out


def test_finding_references_correct_bizrule() -> None:
    out = format_comment(_report(findings_per_bizrule=[
        ("RULE_A", [_finding("SR001", "error", 11, "a-err")]),
        ("RULE_B", [_finding("SR010", "warning", 22, "b-warn")]),
    ]))
    assert "`RULE_A:11`" in out
    assert "`RULE_B:22`" in out
