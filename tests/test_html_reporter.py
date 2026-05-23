"""Tests for the self-contained HTML report generator."""
from __future__ import annotations

import re

import pytest

from reviewer.reporters.html_reporter import to_html_string, write_html


def _finding(rule_id="SR001", severity="error", line=1, message="msg",
             category="logic") -> dict:
    return {
        "rule_id": rule_id,
        "category": category,
        "severity": severity,
        "line": line,
        "message": message,
    }


def _bizrule(name: str, findings: list[dict]) -> dict:
    return {"name": name, "finding_count": len(findings), "findings": findings}


def _report(*, packs: list[dict] | None = None,
            total: int | None = None,
            by_severity: dict | None = None,
            by_category: dict | None = None,
            directory: str = "/work",
            version: str = "1.0.0",
            timestamp: str = "2026-05-23T00:00:00Z") -> dict:
    packs = packs or []
    if total is None:
        total = sum(
            len(br.get("findings", []))
            for p in packs for br in p.get("bizrules", [])
        )
    if by_severity is None:
        by_severity = {"error": 0, "warning": 0, "info": 0}
        for p in packs:
            for br in p.get("bizrules", []):
                for f in br.get("findings", []):
                    by_severity[f["severity"]] = by_severity.get(f["severity"], 0) + 1
    if by_category is None:
        by_category = {}
        for p in packs:
            for br in p.get("bizrules", []):
                for f in br.get("findings", []):
                    by_category[f["category"]] = by_category.get(f["category"], 0) + 1
    bizrule_count = sum(len(p.get("bizrules", [])) for p in packs)
    return {
        "metadata": {
            "tool": "REVIEWER",
            "version": version,
            "timestamp": timestamp,
            "directory": directory,
        },
        "summary": {
            "total": total,
            "by_severity": by_severity,
            "by_category": by_category,
            "pack_count": len(packs),
            "bizrule_count": bizrule_count,
        },
        "packs": packs,
    }


def test_empty_report_renders_no_issues_message() -> None:
    out = to_html_string(_report())
    assert "✅ No issues found." in out
    assert 'class="empty-block"' in out
    assert 'class="pack"' not in out


def test_summary_banner_shows_correct_counts() -> None:
    packs = [{
        "pack_file": "a.pack.xml",
        "bizrules": [_bizrule("R", [
            _finding(severity="error"),
            _finding(severity="warning"),
            _finding(severity="warning"),
            _finding(severity="info"),
        ])],
    }]
    out = to_html_string(_report(packs=packs))
    assert "🔴 1 errors" in out
    assert "🟡 2 warnings" in out
    assert "🔵 1 info" in out
    assert "<strong>Total findings:</strong> 4" in out
    assert "<strong>Packs:</strong> 1" in out
    assert "<strong>BizRules:</strong> 1" in out


def test_each_pack_renders_as_section() -> None:
    packs = [
        {"pack_file": "a.pack.xml",
         "bizrules": [_bizrule("RA", [_finding()])]},
        {"pack_file": "b.pack.xml",
         "bizrules": [_bizrule("RB", [_finding()])]},
    ]
    out = to_html_string(_report(packs=packs))
    assert out.count('<section class="pack"') == 2
    assert "a.pack.xml" in out
    assert "b.pack.xml" in out
    assert "RA" in out
    assert "RB" in out


def test_bizrule_with_zero_findings_is_omitted() -> None:
    packs = [{
        "pack_file": "a.pack.xml",
        "bizrules": [
            _bizrule("KEEP_ME", [_finding()]),
            _bizrule("SKIP_ME", []),
        ],
    }]
    out = to_html_string(_report(packs=packs))
    assert "KEEP_ME" in out
    assert "SKIP_ME" not in out


def test_pack_with_zero_findings_shows_clean_message() -> None:
    # Pack has bizrules but none have findings.
    packs = [{
        "pack_file": "empty.pack.xml",
        "bizrules": [_bizrule("R", [])],
    }]
    # Force overall total > 0 elsewhere by adding a second pack with one finding,
    # so we hit the per-pack-empty branch (total==0 short-circuits earlier).
    packs.append({
        "pack_file": "other.pack.xml",
        "bizrules": [_bizrule("X", [_finding()])],
    })
    out = to_html_string(_report(packs=packs))
    assert "✅ No issues found in this pack." in out
    assert "empty.pack.xml" in out


def test_finding_rendered_in_correct_table_row() -> None:
    packs = [{
        "pack_file": "a.pack.xml",
        "bizrules": [_bizrule("R", [
            _finding(rule_id="SR042", severity="warning", line=17,
                     message="suspicious", category="security"),
        ])],
    }]
    out = to_html_string(_report(packs=packs))
    assert "SR042" in out
    assert ">17<" in out
    assert "security" in out
    assert "suspicious" in out
    # All inside a <tr ...> row.
    assert re.search(r"<tr[^>]*>[^<]*<td[^>]*>17</td>", out)


def test_severity_emojis_present() -> None:
    packs = [{
        "pack_file": "a.pack.xml",
        "bizrules": [_bizrule("R", [
            _finding(severity="error"),
            _finding(severity="warning"),
            _finding(severity="info"),
        ])],
    }]
    out = to_html_string(_report(packs=packs))
    assert "🔴" in out
    assert "🟡" in out
    assert "🔵" in out


def test_severity_class_applied_for_styling() -> None:
    packs = [{
        "pack_file": "a.pack.xml",
        "bizrules": [_bizrule("R", [
            _finding(severity="error"),
            _finding(severity="warning"),
            _finding(severity="info"),
        ])],
    }]
    out = to_html_string(_report(packs=packs))
    assert 'class="severity-error"' in out
    assert 'class="severity-warning"' in out
    assert 'class="severity-info"' in out


def test_html_escaping_prevents_xss() -> None:
    payload = "<script>alert(1)</script>"
    packs = [{
        "pack_file": "a.pack.xml",
        "bizrules": [_bizrule("R", [_finding(message=payload)])],
    }]
    out = to_html_string(_report(packs=packs))
    # Raw payload must NOT appear (as live HTML).
    assert payload not in out
    # Escaped form must appear.
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in out


def test_html_escaping_handles_ampersand() -> None:
    packs = [{
        "pack_file": "a&b.pack.xml",
        "bizrules": [_bizrule("R&D", [_finding(message="A & B")])],
    }]
    out = to_html_string(_report(packs=packs))
    assert "A &amp; B" in out
    assert "a&amp;b.pack.xml" in out
    assert "R&amp;D" in out


def test_french_characters_preserved_in_output() -> None:
    msg = "Règle non conforme — caractère é à l'écran"
    packs = [{
        "pack_file": "français.pack.xml",
        "bizrules": [_bizrule("RÉGLE_A", [_finding(message=msg)])],
    }]
    out = to_html_string(_report(packs=packs))
    assert "Règle non conforme" in out
    assert "caractère é à" in out
    assert "français.pack.xml" in out
    assert "RÉGLE_A" in out


def test_table_of_contents_omitted_for_single_pack() -> None:
    packs = [{
        "pack_file": "only.pack.xml",
        "bizrules": [_bizrule("R", [_finding()])],
    }]
    out = to_html_string(_report(packs=packs))
    assert '<nav class="toc">' not in out


def test_table_of_contents_present_for_multiple_packs() -> None:
    packs = [
        {"pack_file": "a.pack.xml",
         "bizrules": [_bizrule("RA", [_finding()])]},
        {"pack_file": "b.pack.xml",
         "bizrules": [_bizrule("RB", [_finding()])]},
    ]
    out = to_html_string(_report(packs=packs))
    assert '<nav class="toc">' in out
    assert 'href="#pack-0' in out
    assert 'href="#pack-1' in out


def test_footer_contains_version_and_timestamp() -> None:
    out = to_html_string(_report(version="9.9.9", timestamp="2099-01-02T03:04:05Z"))
    assert "<footer" in out
    assert "Generated by REVIEWER v9.9.9" in out
    assert "2099-01-02T03:04:05Z" in out


def test_write_html_creates_parent_dirs(tmp_path) -> None:
    out_path = tmp_path / "nested" / "deep" / "report.html"
    write_html(_report(), out_path)
    assert out_path.is_file()
    content = out_path.read_text(encoding="utf-8")
    assert content.startswith("<!DOCTYPE html>")
    assert "REVIEWER Report" in content


def test_no_external_resources() -> None:
    packs = [{
        "pack_file": "a.pack.xml",
        "bizrules": [_bizrule("R", [_finding()])],
    }]
    out = to_html_string(_report(packs=packs))
    assert "http://" not in out
    assert "https://" not in out
    # Protocol-relative URLs like "//cdn.example.com/x.css".
    assert not re.search(r'(?:href|src)\s*=\s*["\']//', out)
    # No CSS @import or url(...) references.
    assert "@import" not in out
    assert "url(" not in out


def test_output_is_valid_html() -> None:
    out = to_html_string(_report())
    assert out.startswith("<!DOCTYPE html>")
    assert "<html" in out
    assert "<head>" in out
    assert "<body>" in out
    assert "</html>" in out
    assert "<title>REVIEWER Report</title>" in out


def test_neoxam_branding_present() -> None:
    from reviewer.reporters.html_reporter import to_html_string
    out = to_html_string(_report())
    # Tagline present.
    assert "Static Analysis for BizRule" in out
    # Footer brand line: text fragments "Powered by" and "REVIEWER"
    # both appear, separated by the wordmark image.
    assert "Powered by" in out
    assert 'class="powered-by"' in out
    # NeoXam icon embedded as base64 data URI (header).
    assert "data:image/png;base64," in out
    # Magnifying glass SVG still present as accent.
    assert "<svg" in out
