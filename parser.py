# parser.py
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Trigger:
    """One row of a SMARTRULE's trigger table.

    ``trigger_type`` is the numeric ID from ``<TRIGGER_TYPE>`` (per the
    ``RULE_TRIGGER_TYPE`` enum in ``schema.xml``); ``None`` if the
    field is missing, empty, or non-numeric.

    ``trigger_object`` is the value of ``<TRIGGER_OBJECT>``; the empty
    string if missing.
    """
    trigger_type: int | None
    trigger_object: str


class BizRule:
    def __init__(
        self,
        name,
        comment,
        scope,
        script,
        display_names=None,
        triggers=(),
    ):
        self.name = name
        self.comment = comment
        self.scope = scope
        self.script = script
        # Defensive copies so callers can't mutate our state via the
        # references they passed in.
        self.display_names = dict(display_names) if display_names else {}
        self.triggers = tuple(triggers)


# Strip an optional CDATA wrapper from a captured payload. Real packs
# nest CDATA inconsistently — some payloads are wrapped, some aren't.
_CDATA_RE = re.compile(
    r"^\s*<!\[CDATA\[(?P<inner>.*?)\]\]>\s*$",
    flags=re.DOTALL,
)


def _strip_cdata(text: str) -> str:
    if text is None:
        return ""
    m = _CDATA_RE.match(text)
    if m:
        return m.group("inner").strip()
    return text.strip()


# Real packs use the NeoXam DataHub R_/T_ wrapper convention for
# repeating sub-tables. We match the row-level element so an outer
# T_SMARTRULE_NAME / T_SMARTRULE_TRIGGER block with zero rows yields
# zero entries.
_R_NAME_RE = re.compile(
    r"<R_SMARTRULE_NAME\b[^>]*>(.*?)</R_SMARTRULE_NAME>",
    flags=re.DOTALL | re.IGNORECASE,
)
_R_TRIGGER_RE = re.compile(
    r"<R_SMARTRULE_TRIGGER\b[^>]*>(.*?)</R_SMARTRULE_TRIGGER>",
    flags=re.DOTALL | re.IGNORECASE,
)
_NAME_TEXT_RE = re.compile(
    r"<NAME\b[^>]*>(.*?)</NAME>",
    flags=re.DOTALL | re.IGNORECASE,
)
_NAME_LANG_RE = re.compile(
    r"<NAME_LANGUAGE\b[^>]*>(.*?)</NAME_LANGUAGE>",
    flags=re.DOTALL | re.IGNORECASE,
)
_TRIGGER_TYPE_RE = re.compile(
    r"<TRIGGER_TYPE\b[^>]*>(.*?)</TRIGGER_TYPE>",
    flags=re.DOTALL | re.IGNORECASE,
)
_TRIGGER_OBJECT_RE = re.compile(
    r"<TRIGGER_OBJECT\b[^>]*>(.*?)</TRIGGER_OBJECT>",
    flags=re.DOTALL | re.IGNORECASE,
)


def _parse_int_or_none(text: str) -> int | None:
    """Best-effort int parse. Returns ``None`` for empty / non-numeric
    payloads — callers decide whether that's an error.
    """
    s = _strip_cdata(text)
    if not s:
        return None
    try:
        return int(s)
    except ValueError:
        return None


def _extract_display_names(block: str) -> dict[int, str]:
    """Extract ``{NAME_LANGUAGE: NAME}`` from a SMARTRULE block.

    Skips entries whose NAME is empty, and silently ignores entries
    with missing or non-numeric NAME_LANGUAGE — the data-quality
    rules (SR011, SR060) live in the checks layer, not here.
    """
    out: dict[int, str] = {}
    for body in _R_NAME_RE.findall(block):
        lang_match = _NAME_LANG_RE.search(body)
        if lang_match is None:
            continue
        lang = _parse_int_or_none(lang_match.group(1))
        if lang is None:
            continue
        name_match = _NAME_TEXT_RE.search(body)
        if name_match is None:
            continue
        name = _strip_cdata(name_match.group(1))
        if not name:
            continue
        out[lang] = name
    return out


def _extract_triggers(block: str) -> tuple[Trigger, ...]:
    """Extract a Trigger() per R_SMARTRULE_TRIGGER row.

    A row with missing inner fields still produces a ``Trigger`` with
    ``trigger_type=None`` / ``trigger_object=""`` — the relevant check
    decides whether that's a problem.
    """
    out: list[Trigger] = []
    for body in _R_TRIGGER_RE.findall(block):
        type_match = _TRIGGER_TYPE_RE.search(body)
        trigger_type: int | None = (
            _parse_int_or_none(type_match.group(1))
            if type_match is not None
            else None
        )
        obj_match = _TRIGGER_OBJECT_RE.search(body)
        trigger_object = (
            _strip_cdata(obj_match.group(1))
            if obj_match is not None
            else ""
        )
        out.append(
            Trigger(trigger_type=trigger_type, trigger_object=trigger_object)
        )
    return tuple(out)


def extract_bizrules(xml_path):
    with open(xml_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Find all complete <SMARTRULE>...</SMARTRULE> blocks
    smartrules = re.findall(
        r"<SMARTRULE\b.*?>.*?</SMARTRULE>",
        content,
        flags=re.DOTALL | re.IGNORECASE
    )

    rules = []

    for block in smartrules:
        # Extract FIND attribute as scope
        scope_match = re.search(r'FIND="([^"]*)"', block, flags=re.IGNORECASE)
        scope = scope_match.group(1) if scope_match else ""

        # Extract RULE_CODE
        code_match = re.search(
            r"<RULE_CODE.*?>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</RULE_CODE>",
            block,
            flags=re.DOTALL | re.IGNORECASE
        )
        code = code_match.group(1).strip() if code_match else ""

        # Extract USER_COMMENT
        comment_match = re.search(
            r"<USER_COMMENT.*?>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</USER_COMMENT>",
            block,
            flags=re.DOTALL | re.IGNORECASE
        )
        comment = comment_match.group(1).strip() if comment_match else ""

        # Extract IMPACT script
        impact_match = re.search(
            r"<IMPACT.*?>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</IMPACT>",
            block,
            flags=re.DOTALL | re.IGNORECASE
        )
        impact = impact_match.group(1).strip() if impact_match else ""

        rules.append(BizRule(
            name=code,
            comment=comment,
            scope=scope,
            script=impact,
            display_names=_extract_display_names(block),
            triggers=_extract_triggers(block),
        ))

    return rules
