"""Tests for reviewer.ast.tokenizer."""
from __future__ import annotations

from pathlib import Path

import pytest

from reviewer.ast.tokenizer import TokenizeError, tokenize
from reviewer.ast.tokens import Token, TokenKind


# ── Helpers ──────────────────────────────────────────────────────────


def kinds(src: str) -> list[TokenKind]:
    return [t.kind for t in tokenize(src)]


# ── Operators & punctuation ──────────────────────────────────────────


@pytest.mark.parametrize(
    "src,expected",
    [
        (":=", TokenKind.OP_ASSIGN),
        ("?=", TokenKind.OP_COND_ASSIGN),
        ("=", TokenKind.OP_EQ),
        ("!=", TokenKind.OP_NEQ),
        ("<", TokenKind.OP_LT),
        ("<=", TokenKind.OP_LE),
        (">", TokenKind.OP_GT),
        (">=", TokenKind.OP_GE),
        ("+", TokenKind.OP_PLUS),
        ("-", TokenKind.OP_MINUS),
        ("*", TokenKind.OP_STAR),
        ("/", TokenKind.OP_SLASH),
        ("{", TokenKind.LBRACE),
        ("}", TokenKind.RBRACE),
        ("(", TokenKind.LPAREN),
        (")", TokenKind.RPAREN),
        ("[", TokenKind.LBRACKET),
        ("]", TokenKind.RBRACKET),
        (".", TokenKind.DOT),
        (",", TokenKind.COMMA),
        (";", TokenKind.SEMI),
    ],
)
def test_single_operator_token(src: str, expected: TokenKind) -> None:
    toks = tokenize(src)
    assert toks[0].kind is expected
    assert toks[-1].kind is TokenKind.EOF


def test_assignment_vs_equality_distinguished() -> None:
    # `:=` vs `=` must not collapse.
    toks = tokenize("x := y = z")
    assert [t.kind for t in toks[:-1]] == [
        TokenKind.IDENT,
        TokenKind.OP_ASSIGN,
        TokenKind.IDENT,
        TokenKind.OP_EQ,
        TokenKind.IDENT,
    ]


def test_comparison_operators_longest_match() -> None:
    toks = tokenize("a <= b >= c != d < e > f")
    assert [t.kind for t in toks[:-1]] == [
        TokenKind.IDENT, TokenKind.OP_LE,
        TokenKind.IDENT, TokenKind.OP_GE,
        TokenKind.IDENT, TokenKind.OP_NEQ,
        TokenKind.IDENT, TokenKind.OP_LT,
        TokenKind.IDENT, TokenKind.OP_GT,
        TokenKind.IDENT,
    ]


# ── Keywords ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "kw,kind",
    [
        ("if", TokenKind.KW_IF),
        ("else", TokenKind.KW_ELSE),
        ("while", TokenKind.KW_WHILE),
        ("until", TokenKind.KW_UNTIL),
        ("do", TokenKind.KW_DO),
        ("for", TokenKind.KW_FOR),
        ("foreach", TokenKind.KW_FOREACH),
        ("in", TokenKind.KW_IN),
        ("to", TokenKind.KW_TO),
        ("downto", TokenKind.KW_DOWNTO),
        ("return", TokenKind.KW_RETURN),
        ("skip", TokenKind.KW_SKIP),
        ("abort", TokenKind.KW_ABORT),
        ("try", TokenKind.KW_TRY),
        ("onerror", TokenKind.KW_ONERROR),
        ("and", TokenKind.KW_AND),
        ("or", TokenKind.KW_OR),
    ],
)
def test_keywords_case_insensitive(kw: str, kind: TokenKind) -> None:
    for variant in (kw, kw.upper(), kw.title()):
        toks = tokenize(variant)
        assert toks[0].kind is kind, f"{variant} should match {kind}"
        # Original casing is preserved in token value.
        assert toks[0].value == variant


def test_identifier_preserves_case() -> None:
    toks = tokenize("Contrib contrib")
    assert toks[0].kind is TokenKind.IDENT
    assert toks[0].value == "Contrib"
    assert toks[1].value == "contrib"


# ── Numbers ──────────────────────────────────────────────────────────


def test_integer_number() -> None:
    toks = tokenize("42")
    assert toks[0].kind is TokenKind.NUMBER
    assert toks[0].value == "42"


def test_decimal_number() -> None:
    toks = tokenize("3.14")
    assert toks[0].kind is TokenKind.NUMBER
    assert toks[0].value == "3.14"


# ── String literals ──────────────────────────────────────────────────


def test_double_quoted_string() -> None:
    toks = tokenize('"hello"')
    assert toks[0].kind is TokenKind.STRING
    assert toks[0].value == "hello"


def test_single_quoted_string() -> None:
    toks = tokenize("'world'")
    assert toks[0].kind is TokenKind.STRING
    assert toks[0].value == "world"


def test_string_containing_comment_marker_is_not_a_comment() -> None:
    toks = tokenize('"// not a comment"')
    assert toks[0].kind is TokenKind.STRING
    assert toks[0].value == "// not a comment"
    assert toks[1].kind is TokenKind.EOF


def test_string_containing_keywords_stays_string() -> None:
    toks = tokenize('"if while return foreach"')
    assert toks[0].kind is TokenKind.STRING
    assert toks[0].value == "if while return foreach"


# ── Comments ─────────────────────────────────────────────────────────


def test_full_line_comment_is_discarded() -> None:
    toks = tokenize("// just a comment\n")
    assert [t.kind for t in toks] == [TokenKind.EOF]


def test_end_of_line_comment_is_discarded() -> None:
    toks = tokenize("x := 1; // trailing\n")
    assert [t.kind for t in toks[:-1]] == [
        TokenKind.IDENT,
        TokenKind.OP_ASSIGN,
        TokenKind.NUMBER,
        TokenKind.SEMI,
    ]


def test_comment_between_statements() -> None:
    src = "a := 1;\n// note\nb := 2;"
    toks = tokenize(src)
    assert [t.kind for t in toks[:-1]] == [
        TokenKind.IDENT, TokenKind.OP_ASSIGN, TokenKind.NUMBER, TokenKind.SEMI,
        TokenKind.IDENT, TokenKind.OP_ASSIGN, TokenKind.NUMBER, TokenKind.SEMI,
    ]


# ── Line / column accuracy ──────────────────────────────────────────


def test_line_column_accuracy_multiline() -> None:
    src = "a := 1;\n  b := 2;"
    toks = tokenize(src)
    a, _, one, _, b, _, two, *_ = toks
    assert (a.line, a.col) == (1, 1)
    assert (one.line, one.col) == (1, 6)
    assert (b.line, b.col) == (2, 3)
    assert (two.line, two.col) == (2, 8)


# ── Error path ──────────────────────────────────────────────────────


def test_unterminated_string_raises_at_open_quote() -> None:
    with pytest.raises(TokenizeError) as exc:
        tokenize('   "oops')
    assert exc.value.line == 1
    assert exc.value.col == 4


def test_empty_input_yields_only_eof() -> None:
    toks = tokenize("")
    assert len(toks) == 1
    assert toks[0].kind is TokenKind.EOF
    assert (toks[0].line, toks[0].col) == (1, 1)


def test_mixed_whitespace_is_skipped() -> None:
    # Spaces, tabs, CRs, and newlines around a single token.
    toks = tokenize("  \t\r\n  \t x \r\n\t  ")
    assert [t.kind for t in toks] == [TokenKind.IDENT, TokenKind.EOF]
    assert toks[0].value == "x"
    # `x` sits on the second logical line after the leading newline.
    assert toks[0].line == 2


def test_invalid_character_raises_with_position() -> None:
    with pytest.raises(TokenizeError) as exc:
        tokenize("x := @")
    assert exc.value.line == 1
    assert exc.value.col == 6
    assert "@" in exc.value.message


# ── Real fixtures ───────────────────────────────────────────────────


FIXTURES = Path(__file__).parent / "fixtures" / "smartrules"


@pytest.mark.parametrize(
    "fixture_name",
    [
        "update_document_process.smartrule",
        "compute_template_order.smartrule",
    ],
)
def test_tokenize_real_fixture(fixture_name: str) -> None:
    src = (FIXTURES / fixture_name).read_text(encoding="utf-8")
    toks = tokenize(src)
    assert toks[-1].kind is TokenKind.EOF
    # Sanity: real scripts produce many tokens.
    assert len(toks) > 50
