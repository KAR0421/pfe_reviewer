"""Tests for reviewer.ast.parser (Phase 2 minimum subset)."""
from __future__ import annotations

import pytest

from reviewer.ast.nodes import (
    AbortStmt,
    AssignStmt,
    BinaryOp,
    Block,
    Call,
    ExprStmt,
    FieldAccess,
    Identifier,
    IfStmt,
    NumberLit,
    ReturnStmt,
    Script,
    SkipStmt,
    StringLit,
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


def test_missing_semicolon_raises_parse_error() -> None:
    with pytest.raises(ParseError) as exc:
        parse("x := 1")
    # The error position points at the EOF where ';' was expected.
    assert exc.value.expected.startswith("';'")


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
