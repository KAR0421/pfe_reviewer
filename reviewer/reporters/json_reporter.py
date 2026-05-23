"""JSON reporter for review findings.

Schema (stable; consumed by external tooling such as the future
Bitbucket PR integration and dashboards):

```
{
  "metadata": {
    "tool":      "REVIEWER",
    "version":   "<semver string>",
    "timestamp": "<ISO-8601 UTC with Z suffix>",
    "directory": "<absolute resolved path searched>"
  },
  "summary": {
    "total":         <int>,
    "by_severity":   {"error": <int>, "warning": <int>, "info": <int>},
    "by_category":   {"<category>": <int>, ...},
    "pack_count":    <int>,
    "bizrule_count": <int>
  },
  "packs": [
    {
      "pack_file": "<basename>",
      "bizrules": [
        {
          "name":          "<RULE_CODE>",
          "finding_count": <int>,
          "findings": [
            {
              "rule_id":  "<SR###>",
              "category": "<category>",
              "severity": "error" | "warning" | "info",
              "line":     <int>,            // 0 if not source-attributable
              "message":  "<text>"
            }
          ]
        }
      ]
    }
  ]
}
```

Within each BizRule, findings are sorted by ``(line, rule_id)`` for
deterministic, diffable output. Packs preserve the input order
(typically directory glob order, already sorted by ``main.py``).

The ``by_severity`` block always contains all three severities (zero
when unused). The ``by_category`` block only contains categories that
appear at least once in this run.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


__all__ = ["TOOL_NAME", "TOOL_VERSION", "to_json_dict", "write_json"]


TOOL_NAME = "REVIEWER"
TOOL_VERSION = "1.0.0"


def to_json_dict(
    packs_with_reports: Iterable[tuple[str, list[tuple[object, object]]]],
    *,
    directory: str = ".",
    timestamp: str | None = None,
) -> dict:
    """Build the JSON-serialisable dict for a review run.

    ``packs_with_reports`` is an iterable of
    ``(pack_file_name, [(bizrule, report), ...])`` tuples. Each
    ``report`` must expose a ``findings`` iterable of objects with
    ``rule_id``, ``category``, ``severity``, ``line`` and ``message``
    attributes; ``bizrule`` only needs a ``name`` attribute.

    Pure function. ``timestamp`` defaults to the current UTC time in
    ISO-8601 with a ``Z`` suffix; pass an explicit value for
    deterministic tests.
    """
    if timestamp is None:
        timestamp = (
            datetime.now(timezone.utc)
            .replace(microsecond=0)
            .strftime("%Y-%m-%dT%H:%M:%SZ")
        )

    packs_list: list[dict] = []
    total = 0
    by_severity = {"error": 0, "warning": 0, "info": 0}
    by_category: dict[str, int] = {}
    bizrule_count = 0

    for pack_file, br_reports in packs_with_reports:
        bizrules_out: list[dict] = []
        for br, report in br_reports:
            bizrule_count += 1
            findings_sorted = sorted(
                report.findings,
                key=lambda f: (f.line if f.line is not None else 0, f.rule_id),
            )
            findings_out: list[dict] = []
            for f in findings_sorted:
                findings_out.append(
                    {
                        "rule_id": f.rule_id,
                        "category": f.category,
                        "severity": f.severity,
                        "line": f.line if f.line is not None else 0,
                        "message": f.message,
                    }
                )
                total += 1
                if f.severity in by_severity:
                    by_severity[f.severity] += 1
                else:
                    # Unknown severity — surface it instead of dropping it.
                    by_severity[f.severity] = by_severity.get(f.severity, 0) + 1
                by_category[f.category] = by_category.get(f.category, 0) + 1
            bizrules_out.append(
                {
                    "name": br.name,
                    "finding_count": len(findings_out),
                    "findings": findings_out,
                }
            )
        packs_list.append({"pack_file": pack_file, "bizrules": bizrules_out})

    return {
        "metadata": {
            "tool": TOOL_NAME,
            "version": TOOL_VERSION,
            "timestamp": timestamp,
            "directory": directory,
        },
        "summary": {
            "total": total,
            "by_severity": by_severity,
            "by_category": by_category,
            "pack_count": len(packs_list),
            "bizrule_count": bizrule_count,
        },
        "packs": packs_list,
    }


def write_json(dict_data: dict, output_path: str | Path) -> None:
    """Write ``dict_data`` to ``output_path`` as UTF-8 JSON, indented
    by 2 spaces, preserving non-ASCII characters verbatim.
    """
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(dict_data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
