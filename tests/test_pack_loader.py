"""Tests for the XML pack loader (parser.py).

Covers extraction of the four classic BizRule fields plus the two new
fields (display_names, triggers) added for the upcoming SR011, SR060,
SR061, SR062 checks.

Real packs use the NeoXam DataHub R_/T_ wrapper convention: rows live
in ``<R_SMARTRULE_NAME>`` / ``<R_SMARTRULE_TRIGGER>`` elements with
child fields, not attributes. The fixtures here mirror that shape.
"""
from __future__ import annotations

from pathlib import Path

from parser import BizRule, Trigger, extract_bizrules


REPO_ROOT = Path(__file__).resolve().parent.parent


def _write(tmp_path: Path, body: str) -> Path:
    """Wrap ``body`` in the minimal HEAD/BODY/RESULT shell and write
    it to ``pack.xml`` under ``tmp_path``."""
    p = tmp_path / "pack.xml"
    p.write_text(
        "<?xml version='1.0' encoding=\"UTF-8\" ?>\n"
        "<HEAD><PACKAGE>P</PACKAGE></HEAD>\n"
        "<BODY>\n"
        "<RESULT MODE=\"XML\" ACTION=\"GETOBJECTS\" VERSION=\"2\" CHARSET=\"UTF8\">\n"
        + body
        + "\n</RESULT>\n</BODY>\n",
        encoding="utf-8",
    )
    return p


def test_extract_full_bizrule_with_names_and_trigger(tmp_path: Path) -> None:
    """All six fields populate from a well-formed SMARTRULE block."""
    body = """
<SMARTRULE FIND="RULE_CODE='UPDATE_DOC'" USER="alice" UPDATE_DATE="01/01/2026" LABEL="Lbl">
<RULE_CODE><![CDATA[UPDATE_DOC]]></RULE_CODE>
<USER_COMMENT><![CDATA[update the doc]]></USER_COMMENT>
<IMPACT><![CDATA[x := 1;]]></IMPACT>
<T_SMARTRULE_NAME>
<R_SMARTRULE_NAME>
<NAME><![CDATA[Update doc EN]]></NAME>
<NAME_LANGUAGE>0</NAME_LANGUAGE>
</R_SMARTRULE_NAME>
<R_SMARTRULE_NAME>
<NAME><![CDATA[Mise a jour FR]]></NAME>
<NAME_LANGUAGE>1</NAME_LANGUAGE>
</R_SMARTRULE_NAME>
</T_SMARTRULE_NAME>
<T_SMARTRULE_TRIGGER>
<R_SMARTRULE_TRIGGER>
<TRIGGER_OBJECT><![CDATA[DOCUMENT]]></TRIGGER_OBJECT>
<TRIGGER_TYPE>10</TRIGGER_TYPE>
</R_SMARTRULE_TRIGGER>
</T_SMARTRULE_TRIGGER>
</SMARTRULE>
"""
    pack = _write(tmp_path, body)
    rules = extract_bizrules(str(pack))

    assert len(rules) == 1
    br = rules[0]
    # Classic fields untouched.
    assert br.name == "UPDATE_DOC"
    assert br.comment == "update the doc"
    assert br.scope == "RULE_CODE='UPDATE_DOC'"
    assert br.script == "x := 1;"
    # New fields.
    assert br.display_names == {0: "Update doc EN", 1: "Mise a jour FR"}
    assert br.triggers == (
        Trigger(trigger_type=10, trigger_object="DOCUMENT"),
    )


def test_extract_smartrule_without_any_names(tmp_path: Path) -> None:
    """A rule with no SMARTRULE_NAME yields display_names == {}."""
    body = """
<SMARTRULE FIND="RULE_CODE='X'">
<RULE_CODE><![CDATA[X]]></RULE_CODE>
<USER_COMMENT><![CDATA[c]]></USER_COMMENT>
<IMPACT><![CDATA[x := 1;]]></IMPACT>
</SMARTRULE>
"""
    pack = _write(tmp_path, body)
    rules = extract_bizrules(str(pack))

    assert len(rules) == 1
    assert rules[0].display_names == {}
    assert rules[0].triggers == ()


def test_extract_trigger_with_empty_trigger_type(tmp_path: Path) -> None:
    """Empty ``<TRIGGER_TYPE></TRIGGER_TYPE>`` → trigger_type=None,
    trigger_object preserved.
    """
    body = """
<SMARTRULE FIND="RULE_CODE='X'">
<RULE_CODE><![CDATA[X]]></RULE_CODE>
<USER_COMMENT><![CDATA[c]]></USER_COMMENT>
<IMPACT><![CDATA[x := 1;]]></IMPACT>
<T_SMARTRULE_TRIGGER>
<R_SMARTRULE_TRIGGER>
<TRIGGER_OBJECT><![CDATA[DOCUMENT]]></TRIGGER_OBJECT>
<TRIGGER_TYPE></TRIGGER_TYPE>
</R_SMARTRULE_TRIGGER>
</T_SMARTRULE_TRIGGER>
</SMARTRULE>
"""
    pack = _write(tmp_path, body)
    rules = extract_bizrules(str(pack))

    assert len(rules) == 1
    assert rules[0].triggers == (
        Trigger(trigger_type=None, trigger_object="DOCUMENT"),
    )


def test_extract_trigger_with_non_numeric_trigger_type(tmp_path: Path) -> None:
    """Non-numeric ``<TRIGGER_TYPE>abc</TRIGGER_TYPE>`` → trigger_type=None.
    The check layer (SR062) decides whether that's a problem.
    """
    body = """
<SMARTRULE FIND="RULE_CODE='X'">
<RULE_CODE><![CDATA[X]]></RULE_CODE>
<USER_COMMENT><![CDATA[c]]></USER_COMMENT>
<IMPACT><![CDATA[x := 1;]]></IMPACT>
<T_SMARTRULE_TRIGGER>
<R_SMARTRULE_TRIGGER>
<TRIGGER_OBJECT><![CDATA[DOCUMENT]]></TRIGGER_OBJECT>
<TRIGGER_TYPE>abc</TRIGGER_TYPE>
</R_SMARTRULE_TRIGGER>
</T_SMARTRULE_TRIGGER>
</SMARTRULE>
"""
    pack = _write(tmp_path, body)
    rules = extract_bizrules(str(pack))

    assert len(rules) == 1
    assert rules[0].triggers == (
        Trigger(trigger_type=None, trigger_object="DOCUMENT"),
    )


def test_real_sample_pack_has_names_and_triggers() -> None:
    """Regression: the real ``sample.pack`` must yield at least
    one display name and at least one trigger on its first BizRule.

    Guards against a future refactor that breaks the R_/T_ wrapper
    handling on actual NeoXam DataHub exports.
    """
    sample = REPO_ROOT / "sample.pack"
    rules = extract_bizrules(str(sample))

    assert rules, "sample.pack extracted no rules"
    br = rules[0]
    assert isinstance(br, BizRule)
    assert br.display_names, (
        "expected at least one SMARTRULE_NAME in the real pack, got "
        f"{br.display_names!r}"
    )
    assert br.triggers, (
        "expected at least one SMARTRULE_TRIGGER in the real pack, got "
        f"{br.triggers!r}"
    )
    # Every trigger must be a proper Trigger instance.
    assert all(isinstance(t, Trigger) for t in br.triggers)
