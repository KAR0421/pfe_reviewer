"""Tests for reviewer.ast.parser (Phase 2 minimum subset)."""
from __future__ import annotations

from pathlib import Path

import pytest

from reviewer.ast.nodes import (
    AbortStmt,
    ArrayIndex,
    AssignStmt,
    BinaryOp,
    Block,
    Call,
    DoWhile,
    ExprStmt,
    FieldAccess,
    ForCStyle,
    ForCounter,
    ForeachList,
    ForeachTable,
    Identifier,
    IfStmt,
    NumberLit,
    ReturnStmt,
    Script,
    SkipStmt,
    StringLit,
    TableSelector,
    TryStmt,
    WhileStmt,
)
from reviewer.ast.parser import ParseError, Parser
from reviewer.ast.tokenizer import tokenize


def parse(src: str) -> Script:
    return Parser(tokenize(src)).parse_script()


# ── Assignment ──────────────────────────────────────────────────────


def test_simple_assignment() -> None:
    script = parse("x := 1;")
    assert len(script.statements) == 1
    stmt = script.statements[0]
    assert isinstance(stmt, AssignStmt)
    assert stmt.op == ":="
    assert isinstance(stmt.target, Identifier) and stmt.target.name == "x"
    assert isinstance(stmt.value, NumberLit) and stmt.value.value == 1
    assert stmt.line == 1


def test_conditional_assignment_op() -> None:
    script = parse("x ?= 1;")
    stmt = script.statements[0]
    assert isinstance(stmt, AssignStmt)
    assert stmt.op == "?="


def test_assign_to_field_access() -> None:
    script = parse("obj.NAME := \"foo\";")
    stmt = script.statements[0]
    assert isinstance(stmt, AssignStmt)
    assert isinstance(stmt.target, FieldAccess)
    assert stmt.target.field == "NAME"
    assert isinstance(stmt.value, StringLit)
    assert stmt.value.value == "foo"


# ── Function calls ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    "src,expected_argc",
    [
        ("foo();", 0),
        ("foo(1);", 1),
        ("foo(1, 2, 3, x);", 4),
    ],
)
def test_function_call_arg_count(src: str, expected_argc: int) -> None:
    script = parse(src)
    stmt = script.statements[0]
    assert isinstance(stmt, ExprStmt)
    assert isinstance(stmt.expr, Call)
    assert len(stmt.expr.args) == expected_argc


def test_method_call_on_object() -> None:
    script = parse("obj.process(1, x);")
    stmt = script.statements[0]
    assert isinstance(stmt, ExprStmt)
    call = stmt.expr
    assert isinstance(call, Call)
    assert isinstance(call.callee, FieldAccess)
    assert call.callee.field == "process"
    assert len(call.args) == 2


# ── If / if-else ───────────────────────────────────────────────────


def test_if_with_single_statement_branch() -> None:
    script = parse("if (x = 1) y := 2;")
    stmt = script.statements[0]
    assert isinstance(stmt, IfStmt)
    assert stmt.else_branch is None
    assert isinstance(stmt.cond, BinaryOp) and stmt.cond.op == "="
    assert isinstance(stmt.then_branch, AssignStmt)


def test_if_with_block_branches() -> None:
    src = """
    if (x = 1) {
        y := 2;
    } else {
        y := 3;
    }
    """
    script = parse(src)
    stmt = script.statements[0]
    assert isinstance(stmt, IfStmt)
    assert isinstance(stmt.then_branch, Block)
    assert isinstance(stmt.else_branch, Block)
    assert len(stmt.then_branch.statements) == 1
    assert len(stmt.else_branch.statements) == 1


# ── Terminators ────────────────────────────────────────────────────


def test_return_with_value() -> None:
    script = parse("return x + 1;")
    stmt = script.statements[0]
    assert isinstance(stmt, ReturnStmt)
    assert isinstance(stmt.value, BinaryOp)
    assert stmt.value.op == "+"


def test_return_without_value() -> None:
    script = parse("return;")
    stmt = script.statements[0]
    assert isinstance(stmt, ReturnStmt)
    assert stmt.value is None


def test_skip_and_abort() -> None:
    script = parse('skip "msg"; abort;')
    s1, s2 = script.statements
    assert isinstance(s1, SkipStmt)
    assert isinstance(s1.value, StringLit) and s1.value.value == "msg"
    assert isinstance(s2, AbortStmt)
    assert s2.value is None


# ── Operator precedence ───────────────────────────────────────────


def test_precedence_multiplicative_over_additive() -> None:
    script = parse("x := 1 + 2 * 3;")
    rhs = script.statements[0].value
    assert isinstance(rhs, BinaryOp) and rhs.op == "+"
    assert isinstance(rhs.right, BinaryOp) and rhs.right.op == "*"


def test_precedence_and_over_or() -> None:
    script = parse("x := a or b and c;")
    rhs = script.statements[0].value
    assert isinstance(rhs, BinaryOp) and rhs.op == "or"
    assert isinstance(rhs.right, BinaryOp) and rhs.right.op == "and"


def test_parens_override_precedence() -> None:
    script = parse("x := (1 + 2) * 3;")
    rhs = script.statements[0].value
    assert isinstance(rhs, BinaryOp) and rhs.op == "*"
    assert isinstance(rhs.left, BinaryOp) and rhs.left.op == "+"


# ── Top-level structure ───────────────────────────────────────────


def test_multiple_top_level_statements_with_line_numbers() -> None:
    src = "a := 1;\nb := 2;\nc := 3;"
    script = parse(src)
    assert len(script.statements) == 3
    assert script.statements[0].line == 1
    assert script.statements[1].line == 2
    assert script.statements[2].line == 3


def test_empty_script_parses() -> None:
    script = parse("")
    assert script.statements == ()


# ── Error path ────────────────────────────────────────────────────


# ── Statement-separator rule (`;` is optional at end-of-line) ────


def test_statement_without_trailing_semicolon_is_valid() -> None:
    """Per the spec, ``;`` is optional when the statement ends the line."""
    script = parse("x := 1")
    assert len(script.statements) == 1
    assert isinstance(script.statements[0], AssignStmt)


def test_two_statements_same_line_without_separator_raises() -> None:
    """``x := 1 y := 2`` lacks the required separator between them."""
    with pytest.raises(ParseError) as exc:
        parse("x := 1 y := 2")
    # Care about *where* the error is, not how the message is phrased.
    assert exc.value.line == 1


def test_two_statements_on_separate_lines_without_semicolons() -> None:
    """Newline alone separates statements; no ``;`` required."""
    script = parse("x := 1\ny := 2\n")
    assert len(script.statements) == 2
    assert all(isinstance(s, AssignStmt) for s in script.statements)


def test_script_ending_without_semicolon_is_valid() -> None:
    """A script may end without a trailing ``;`` on its last statement."""
    script = parse("foo()\nbar()")
    assert len(script.statements) == 2


def test_block_statements_one_per_line_without_semicolons() -> None:
    """``{ x := 1 \\n y := 2 }`` — newline separates inside a block too."""
    script = parse("{\n  x := 1\n  y := 2\n}")
    assert len(script.statements) == 1
    block = script.statements[0]
    assert isinstance(block, Block)
    assert len(block.statements) == 2
    assert all(isinstance(s, AssignStmt) for s in block.statements)


def test_unclosed_paren_raises_parse_error() -> None:
    with pytest.raises(ParseError):
        parse("x := (1 + 2;")


# ── Extra Phase 2 coverage ────────────────────────────────────────


def test_nested_calls() -> None:
    """``f(g(x))`` — outer Call whose first arg is itself a Call."""
    script = parse("f(g(x));")
    stmt = script.statements[0]
    assert isinstance(stmt, ExprStmt)
    outer = stmt.expr
    assert isinstance(outer, Call)
    assert isinstance(outer.callee, Identifier) and outer.callee.name == "f"
    assert len(outer.args) == 1
    inner = outer.args[0]
    assert isinstance(inner, Call)
    assert isinstance(inner.callee, Identifier) and inner.callee.name == "g"
    assert len(inner.args) == 1
    assert isinstance(inner.args[0], Identifier) and inner.args[0].name == "x"


def test_chained_field_access() -> None:
    """``obj.TABLE.FIELD`` — left-associative FieldAccess chain."""
    script = parse("x := obj.TABLE.FIELD;")
    stmt = script.statements[0]
    assert isinstance(stmt, AssignStmt)
    rhs = stmt.value
    assert isinstance(rhs, FieldAccess) and rhs.field == "FIELD"
    assert isinstance(rhs.target, FieldAccess) and rhs.target.field == "TABLE"
    assert isinstance(rhs.target.target, Identifier)
    assert rhs.target.target.name == "obj"


def test_real_snippet_phase2_subset() -> None:
    """Hand-trimmed snippet from sample_pack.xml using only Phase 2 grammar."""
    # Mirrors the head of UPDATE_DOCUMENT_PROCESS, stripped of foreach loops:
    # assignments, calls, field access, an `if`, and a bare `return`.
    src = (
        'contribManagement := getparam("impress.contrib.management");\n'
        "contribution := obj1;\n"
        'validFlag := getListItemId("YES_NO", "Y");\n'
        "levelSdg := obj1.IS_MGMT_COMPANY_LEVEL;\n"
        "if (levelSdg = validFlag) {\n"
        "    msginfo(\"ok\");\n"
        "}\n"
        "return;\n"
    )
    script = parse(src)
    assert len(script.statements) == 6
    # Spot-check a couple of node types and line numbers.
    assert isinstance(script.statements[0], AssignStmt)
    assert script.statements[0].line == 1
    assert isinstance(script.statements[4], IfStmt)
    assert script.statements[4].line == 5
    assert isinstance(script.statements[5], ReturnStmt)
    assert script.statements[5].line == 8


# ── Phase 3: foreach ─────────────────────────────────────────────


def test_foreach_list_form() -> None:
    script = parse("foreach item in items do { x := item; }")
    stmt = script.statements[0]
    assert isinstance(stmt, ForeachList)
    assert stmt.var.name == "item"
    assert isinstance(stmt.iterable, Identifier) and stmt.iterable.name == "items"
    assert isinstance(stmt.body, Block)


def test_foreach_table_form() -> None:
    script = parse("foreach obj.TABLE do { x := 1; }")
    stmt = script.statements[0]
    assert isinstance(stmt, ForeachTable)
    assert isinstance(stmt.target, FieldAccess)
    assert stmt.target.field == "TABLE"
    assert isinstance(stmt.body, Block)


def test_foreach_single_statement_body() -> None:
    script = parse("foreach x in xs do y := x;")
    stmt = script.statements[0]
    assert isinstance(stmt, ForeachList)
    assert isinstance(stmt.body, AssignStmt)


# ── Phase 3: for ─────────────────────────────────────────────────


def test_for_counter_to() -> None:
    script = parse("for i := 1 to 10 do { x := i; }")
    stmt = script.statements[0]
    assert isinstance(stmt, ForCounter)
    assert stmt.var.name == "i"
    assert stmt.direction == "to"
    assert isinstance(stmt.start, NumberLit) and stmt.start.value == 1
    assert isinstance(stmt.end, NumberLit) and stmt.end.value == 10


def test_for_counter_downto() -> None:
    script = parse("for i := 10 downto 1 do x := i;")
    stmt = script.statements[0]
    assert isinstance(stmt, ForCounter)
    assert stmt.direction == "downto"


def test_for_c_style() -> None:
    script = parse("for (i := 0; i < 10; i := i + 1) { x := i; }")
    stmt = script.statements[0]
    assert isinstance(stmt, ForCStyle)
    assert isinstance(stmt.init, AssignStmt)
    assert isinstance(stmt.cond, BinaryOp) and stmt.cond.op == "<"
    assert isinstance(stmt.step, AssignStmt)
    assert isinstance(stmt.body, Block)


# ── Phase 3: while / do-while ────────────────────────────────────


def test_while_loop() -> None:
    script = parse("while (x < 10) x := x + 1;")
    stmt = script.statements[0]
    assert isinstance(stmt, WhileStmt)
    assert isinstance(stmt.cond, BinaryOp) and stmt.cond.op == "<"
    assert isinstance(stmt.body, AssignStmt)


def test_do_while_loop() -> None:
    script = parse("do { x := x + 1; } while (x < 10);")
    stmt = script.statements[0]
    assert isinstance(stmt, DoWhile)
    assert isinstance(stmt.body, Block)
    assert isinstance(stmt.cond, BinaryOp) and stmt.cond.op == "<"


def test_do_while_without_trailing_semicolon() -> None:
    """Per the separator rule, the trailing ';' on do-while is optional."""
    script = parse("do { x := x + 1; } while (x < 10)")
    stmt = script.statements[0]
    assert isinstance(stmt, DoWhile)


# ── Phase 3: try / onerror ───────────────────────────────────────


def test_try_onerror_blocks() -> None:
    script = parse(
        "try { obj.set(\"F\", 0, 0); } onerror { msginfo(\"oops\"); }"
    )
    stmt = script.statements[0]
    assert isinstance(stmt, TryStmt)
    assert isinstance(stmt.try_block, Block)
    assert isinstance(stmt.onerror_block, Block)


def test_try_without_onerror_is_parse_error() -> None:
    with pytest.raises(ParseError) as exc:
        parse("try { x := 1; }")
    assert "onerror" in exc.value.expected


# ── Phase 3+: if/else with no `;` before `else` ──────────────────


def test_if_then_branch_may_omit_semicolon_before_else() -> None:
    """A single-statement then-branch may drop its trailing ``;`` before ``else``.

    Mirrors a real construct found in sample.pack.xml around line 47, where
    a multi-line string-concatenated assignment is followed directly by
    ``else`` with no terminating ``;``.
    """
    src = (
        "if (x = 1)\n"
        "y := y + \"a\"\n"
        "else\n"
        "y := y + \"b\";\n"
    )
    script = parse(src)
    assert len(script.statements) == 1
    stmt = script.statements[0]
    assert isinstance(stmt, IfStmt)
    assert isinstance(stmt.then_branch, AssignStmt)
    assert isinstance(stmt.else_branch, AssignStmt)
    # Sanity: a normal `;`-terminated then-branch still works.
    script2 = parse("if (x = 1) y := 1; else y := 2;")
    assert isinstance(script2.statements[0], IfStmt)


# ── Phase 3: row selector & array index ──────────────────────────


def test_row_selector_in_expression() -> None:
    script = parse("v := process.PARAMETER_VALUE[PARAMETER_NAME = 'pfCode'];")
    rhs = script.statements[0].value
    assert isinstance(rhs, TableSelector)
    assert rhs.field == "PARAMETER_VALUE"
    assert isinstance(rhs.condition, BinaryOp) and rhs.condition.op == "="


def test_array_index() -> None:
    script = parse("v := a[0];")
    rhs = script.statements[0].value
    assert isinstance(rhs, ArrayIndex)
    assert isinstance(rhs.array, Identifier) and rhs.array.name == "a"
    assert isinstance(rhs.index, NumberLit) and rhs.index.value == 0


# ── Phase 3: real fixture mix ────────────────────────────────────


def test_real_fixture_mix() -> None:
    """Trimmed BizRule body exercising foreach, if-else, calls, field access,\n    row selector, array index, and try/onerror."""
    src = (
        "foreach matchingProc in mergedMatchingProcesses do {\n"
        "    pattern := matchingProc[1];\n"
        "    if (process.findRecord(\"PARAMETER_NAME\", \"jurisdiction\")) {\n"
        "        juridictionProcess := process.PARAMETER_VALUE[PARAMETER_NAME = 'jurisdiction'];\n"
        "    } else {\n"
        "        juridictionProcess := \"\";\n"
        "    }\n"
        "    try {\n"
        "        obj.set(\"F\", 0, 0);\n"
        "    } onerror {\n"
        "        msginfo(\"err\");\n"
        "    }\n"
        "}\n"
    )
    script = parse(src)
    assert len(script.statements) == 1
    outer = script.statements[0]
    assert isinstance(outer, ForeachList)
    body = outer.body
    assert isinstance(body, Block)
    # Inside the loop body we expect: AssignStmt, IfStmt, TryStmt.
    assert isinstance(body.statements[0], AssignStmt)
    assert isinstance(body.statements[0].value, ArrayIndex)
    assert isinstance(body.statements[1], IfStmt)
    then_block = body.statements[1].then_branch
    assert isinstance(then_block, Block)
    assert isinstance(then_block.statements[0].value, TableSelector)
    assert isinstance(body.statements[2], TryStmt)


# ── Phase 3: full real fixture from disk ─────────────────────────


FIXTURES = Path(__file__).parent / "fixtures" / "smartrules"


def test_parse_full_update_document_process_fixture() -> None:
    """End-to-end smoke: parse the real fixture without raising.

    Surfaces unsupported constructs *before* Phase 4 so engine work
    isn't blocked by an unexpected parse failure.
    """
    src = (FIXTURES / "update_document_process.smartrule").read_text(encoding="utf-8")
    script = parse(src)
    assert len(script.statements) > 0
