"""Finding and Report dataclasses produced by the engine.

Stable shape consumed by every reporter — do not add fields without
updating the ADR and every reporter.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Finding:
    rule_id: str        # "SR###"
    category: str       # naming|docs|logic|perf|security|deps|logs|scope|lang
    severity: str       # info | warning | error
    line: int | None
    message: str
    bizrule: str        # the RULE_CODE this finding belongs to


@dataclass(frozen=True)
class Report:
    rule_name: str
    findings: tuple[Finding, ...]
    score: int | None = None
