"""Token dataclass and TokenKind enum for the BizRule scripting language."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto


class TokenKind(Enum):
    """Every token kind produced by the tokenizer."""

    # Literals & identifiers
    IDENT = auto()
    NUMBER = auto()
    STRING = auto()

    # Structural
    LBRACE = auto()
    RBRACE = auto()
    LPAREN = auto()
    RPAREN = auto()
    LBRACKET = auto()
    RBRACKET = auto()
    DOT = auto()
    COMMA = auto()
    SEMI = auto()

    # Assignment operators
    OP_ASSIGN = auto()       # :=
    OP_COND_ASSIGN = auto()  # ?=

    # Comparison
    OP_EQ = auto()    # =
    OP_NEQ = auto()   # !=
    OP_LT = auto()    # <
    OP_LE = auto()    # <=
    OP_GT = auto()    # >
    OP_GE = auto()    # >=

    # Arithmetic / concat
    OP_PLUS = auto()
    OP_MINUS = auto()
    OP_STAR = auto()
    OP_SLASH = auto()

    # Keywords
    KW_IF = auto()
    KW_ELSE = auto()
    KW_WHILE = auto()
    KW_UNTIL = auto()
    KW_DO = auto()
    KW_FOR = auto()
    KW_FOREACH = auto()
    KW_IN = auto()
    KW_TO = auto()
    KW_DOWNTO = auto()
    KW_RETURN = auto()
    KW_SKIP = auto()
    KW_ABORT = auto()
    KW_TRY = auto()
    KW_ONERROR = auto()
    KW_AND = auto()
    KW_OR = auto()

    # End marker
    EOF = auto()


# Map lowercase keyword text to TokenKind
KEYWORDS: dict[str, TokenKind] = {
    "if": TokenKind.KW_IF,
    "else": TokenKind.KW_ELSE,
    "while": TokenKind.KW_WHILE,
    "until": TokenKind.KW_UNTIL,
    "do": TokenKind.KW_DO,
    "for": TokenKind.KW_FOR,
    "foreach": TokenKind.KW_FOREACH,
    "in": TokenKind.KW_IN,
    "to": TokenKind.KW_TO,
    "downto": TokenKind.KW_DOWNTO,
    "return": TokenKind.KW_RETURN,
    "skip": TokenKind.KW_SKIP,
    "abort": TokenKind.KW_ABORT,
    "try": TokenKind.KW_TRY,
    "onerror": TokenKind.KW_ONERROR,
    "and": TokenKind.KW_AND,
    "or": TokenKind.KW_OR,
}


@dataclass(frozen=True)
class Token:
    """A single token with position info (1-based line and column)."""

    kind: TokenKind
    value: str
    line: int
    col: int
