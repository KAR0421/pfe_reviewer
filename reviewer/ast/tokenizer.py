"""Tokenizer: source string -> list[Token] for the BizRule scripting language."""
from __future__ import annotations

from .tokens import KEYWORDS, Token, TokenKind


class TokenizeError(Exception):
    """Raised when the tokenizer encounters an unrecoverable error."""

    def __init__(self, line: int, col: int, message: str) -> None:
        self.line = line
        self.col = col
        self.message = message
        super().__init__(f"TokenizeError at {line}:{col}: {message}")


def tokenize(source: str) -> list[Token]:
    """Tokenize *source* into a list of tokens ending with EOF."""
    tokens: list[Token] = []
    pos = 0
    line = 1
    col = 1
    length = len(source)

    while pos < length:
        ch = source[pos]

        # --- Whitespace ---
        if ch in (" ", "\t", "\r"):
            pos += 1
            col += 1
            continue

        if ch == "\n":
            pos += 1
            line += 1
            col = 1
            continue

        # --- Comments (// until end of line) ---
        if ch == "/" and pos + 1 < length and source[pos + 1] == "/":
            pos += 2
            while pos < length and source[pos] != "\n":
                pos += 1
            # newline itself will be consumed on next iteration
            continue

        # --- String literals ---
        if ch in ('"', "'"):
            tok, pos, line, col = _read_string(source, pos, line, col)
            tokens.append(tok)
            continue

        # --- Numbers ---
        if ch.isdigit():
            tok, pos, col = _read_number(source, pos, line, col)
            tokens.append(tok)
            continue

        # --- Multi-char operators (must check before single-char) ---
        # :=
        if ch == ":" and pos + 1 < length and source[pos + 1] == "=":
            tokens.append(Token(TokenKind.OP_ASSIGN, ":=", line, col))
            pos += 2
            col += 2
            continue

        # ?=
        if ch == "?" and pos + 1 < length and source[pos + 1] == "=":
            tokens.append(Token(TokenKind.OP_COND_ASSIGN, "?=", line, col))
            pos += 2
            col += 2
            continue

        # !=
        if ch == "!" and pos + 1 < length and source[pos + 1] == "=":
            tokens.append(Token(TokenKind.OP_NEQ, "!=", line, col))
            pos += 2
            col += 2
            continue

        # <=
        if ch == "<" and pos + 1 < length and source[pos + 1] == "=":
            tokens.append(Token(TokenKind.OP_LE, "<=", line, col))
            pos += 2
            col += 2
            continue

        # >=
        if ch == ">" and pos + 1 < length and source[pos + 1] == "=":
            tokens.append(Token(TokenKind.OP_GE, ">=", line, col))
            pos += 2
            col += 2
            continue

        # --- Single-char operators and punctuation ---
        single: dict[str, TokenKind] = {
            "{": TokenKind.LBRACE,
            "}": TokenKind.RBRACE,
            "(": TokenKind.LPAREN,
            ")": TokenKind.RPAREN,
            "[": TokenKind.LBRACKET,
            "]": TokenKind.RBRACKET,
            ".": TokenKind.DOT,
            ",": TokenKind.COMMA,
            ";": TokenKind.SEMI,
            "=": TokenKind.OP_EQ,
            "<": TokenKind.OP_LT,
            ">": TokenKind.OP_GT,
            "+": TokenKind.OP_PLUS,
            "-": TokenKind.OP_MINUS,
            "*": TokenKind.OP_STAR,
            "/": TokenKind.OP_SLASH,
        }
        if ch in single:
            tokens.append(Token(single[ch], ch, line, col))
            pos += 1
            col += 1
            continue

        # --- Identifiers and keywords ---
        if ch.isalpha() or ch == "_":
            tok, pos, col = _read_ident(source, pos, line, col)
            tokens.append(tok)
            continue

        # --- Unrecognized character ---
        raise TokenizeError(line, col, f"Unexpected character: {ch!r}")

    tokens.append(Token(TokenKind.EOF, "", line, col))
    return tokens


# ── Helpers ──────────────────────────────────────────────────────────


def _read_string(
    source: str, pos: int, line: int, col: int
) -> tuple[Token, int, int, int]:
    """Read a string literal (single or double-quoted). Returns token + updated position."""
    quote = source[pos]
    start_line = line
    start_col = col
    pos += 1
    col += 1
    buf: list[str] = []

    while pos < len(source):
        ch = source[pos]
        if ch == quote:
            value = "".join(buf)
            pos += 1
            col += 1
            return Token(TokenKind.STRING, value, start_line, start_col), pos, line, col
        if ch == "\n":
            buf.append(ch)
            pos += 1
            line += 1
            col = 1
            continue
        buf.append(ch)
        pos += 1
        col += 1

    raise TokenizeError(start_line, start_col, "Unterminated string literal")


def _read_number(
    source: str, pos: int, line: int, col: int
) -> tuple[Token, int, int]:
    """Read an integer or decimal number literal."""
    start = pos
    start_col = col
    while pos < len(source) and source[pos].isdigit():
        pos += 1
        col += 1
    if pos < len(source) and source[pos] == ".":
        pos += 1
        col += 1
        while pos < len(source) and source[pos].isdigit():
            pos += 1
            col += 1
    value = source[start:pos]
    return Token(TokenKind.NUMBER, value, line, start_col), pos, col


def _read_ident(
    source: str, pos: int, line: int, col: int
) -> tuple[Token, int, int]:
    """Read an identifier or keyword (case-insensitive keyword matching)."""
    start = pos
    start_col = col
    while pos < len(source) and (source[pos].isalnum() or source[pos] == "_"):
        pos += 1
        col += 1
    value = source[start:pos]
    kind = KEYWORDS.get(value.lower(), TokenKind.IDENT)
    return Token(kind, value, line, start_col), pos, col
