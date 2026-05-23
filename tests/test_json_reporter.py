"""Tests for the JSON reporter (reviewer/reporters/json_reporter.py)."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from reviewer.reporters.json_reporter import (
    TOOL_NAME,
    TOOL_VERSION,
    to_json_dict,
    write_json,
)


@dataclass
class _F:
    rule_id: str
    category: str
    severity: str
    line: int
    message: str
    bizrule: str = "X"


@dataclass
class _R:
    rule_name: str
    findings: tuple


@dataclass
class _BR:
    name: str


_FIXED_TS = "2026-05-19T15:30:00Z"


def _build(packs):
    return to_json_dict(packs, directory="/abs/path", timestamp=_FIXED_TS)


def test_empty_pack_produces_empty_packs_list() -> None:
    out = _build([])
    assert out["packs"] == []
    assert out["summary"]["total"] == 0
    assert out["summary"]["pack_count"] == 0
    assert out["summary"]["bizrule_count"] == 0
    assert out["summary"]["by_severity"] == {
        "error": 0,
        "warning": 0,
        "info": 0,
    }
    assert out["summary"]["by_category"] == {}
    assert out["metadata"]["tool"] == TOOL_NAME
    assert out["metadata"]["version"] == TOOL_VERSION


def test_finding_appears_in_correct_bizrule_section() -> None:
    br1 = _BR("RULE_A")
    br2 = _BR("RULE_B")
    f1 = _F("SR020", "logic", "error", 3, "tautology", "RULE_A")
    f2 = _F("SR090", "logs", "warning", 7, "log in loop", "RULE_B")
    out = _build([
        ("p1.pack.xml", [(br1, _R("RULE_A", (f1,))), (br2, _R("RULE_B", (f2,)))]),
    ])
    pack = out["packs"][0]
    assert pack["pack_file"] == "p1.pack.xml"
    a, b = pack["bizrules"]
    assert a["name"] == "RULE_A"
    assert a["finding_count"] == 1
    assert a["findings"][0]["rule_id"] == "SR020"
    assert b["name"] == "RULE_B"
    assert b["findings"][0]["rule_id"] == "SR090"


def test_summary_counts_match_total_findings() -> None:
    findings = (
        _F("SR020", "logic", "error", 3, "a"),
        _F("SR021", "logic", "warning", 5, "b"),
        _F("SR090", "logs", "info", 9, "c"),
    )
    out = _build([("p.pack.xml", [(_BR("X"), _R("X", findings))])])
    assert out["summary"]["total"] == 3
    assert out["summary"]["pack_count"] == 1
    assert out["summary"]["bizrule_count"] == 1


def test_severities_summed_correctly() -> None:
    findings = (
        _F("SR020", "logic", "error", 1, "a"),
        _F("SR021", "logic", "error", 2, "b"),
        _F("SR030", "perf", "warning", 3, "c"),
        _F("SR090", "logs", "info", 4, "d"),
        _F("SR091", "logs", "info", 5, "e"),
        _F("SR092", "logs", "info", 6, "f"),
    )
    out = _build([("p.pack.xml", [(_BR("X"), _R("X", findings))])])
    assert out["summary"]["by_severity"] == {
        "error": 2,
        "warning": 1,
        "info": 3,
    }


def test_categories_summed_correctly() -> None:
    findings = (
        _F("SR020", "logic", "error", 1, "a"),
        _F("SR021", "logic", "warning", 2, "b"),
        _F("SR030", "perf", "warning", 3, "c"),
        _F("SR090", "logs", "info", 4, "d"),
    )
    out = _build([("p.pack.xml", [(_BR("X"), _R("X", findings))])])
    assert out["summary"]["by_category"] == {
        "logic": 2,
        "perf": 1,
        "logs": 1,
    }


def test_findings_sorted_by_line_then_rule_id() -> None:
    # Intentionally unsorted input; expect (line, rule_id) order.
    findings = (
        _F("SR090", "logs", "warning", 10, "z"),
        _F("SR020", "logic", "error", 3, "y"),
        _F("SR010", "naming", "info", 3, "x"),  # same line as SR020 → comes first
        _F("SR021", "logic", "warning", 5, "w"),
    )
    out = _build([("p.pack.xml", [(_BR("X"), _R("X", findings))])])
    ids = [f["rule_id"] for f in out["packs"][0]["bizrules"][0]["findings"]]
    assert ids == ["SR010", "SR020", "SR021", "SR090"]


def test_unicode_messages_preserved(tmp_path: Path) -> None:
    msg = "Règle non conforme à la convention française — caractère é"
    findings = (_F("SR010", "naming", "info", 1, msg),)
    out = _build([("p.pack.xml", [(_BR("X"), _R("X", findings))])])
    # In the dict directly.
    assert out["packs"][0]["bizrules"][0]["findings"][0]["message"] == msg
    # And on round-trip through write_json (ensure_ascii=False).
    target = tmp_path / "report.json"
    write_json(out, target)
    raw = target.read_text(encoding="utf-8")
    assert "é" in raw
    assert "française" in raw
    parsed = json.loads(raw)
    assert (
        parsed["packs"][0]["bizrules"][0]["findings"][0]["message"] == msg
    )


def test_timestamp_is_iso8601_z_suffix() -> None:
    # The default (no explicit timestamp) must produce ISO-8601 UTC
    # with a trailing ``Z`` — no microseconds, no offset.
    out = to_json_dict([], directory="/x")
    ts = out["metadata"]["timestamp"]
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", ts), ts
