"""Recursive-descent parser: list[Token] -> Script root AST node.

Phase 2 implements the minimum subset:
- assignments (``:=``, ``?=``)
- expression statements (incl. bare function calls)
- ``if`` / ``if``-``else`` (single statement or block body)
- ``return`` / ``abort`` / ``skip`` (with or without value)
- blocks ``{ ... }``
- expressions: identifiers, number/string literals, field access
  (``obj.FIELD``), binary operators (``+ - * / = != < <= > >= and or``),
  function calls, parenthesized expressions.

Subsequent phases extend this parser; the public entry point and error
type are stable from Phase 2 onward.
"""
from __future__ import annotations

from .nodes import (
    AbortStmt,
    AssignStmt,
    BinaryOp,
    Block,
    Call,
    Expr,
    ExprStmt,
    FieldAccess,
    Identifier,
    IfStmt,
    NumberLit,
    ReturnStmt,
    Script,
    SkipStmt,
    Stmt,
    StringLit,
    UnaryOp,
)
from .tokens import Token, TokenKind


class ParseError(Exception):
    """Raised on unexpected tokens during parsing."""

    def __init__(self, line: int, col: int, expected: str, got: Token) -> None:
        self.line = line
        self.col = col
        self.expected = expected
        self.got = got
        self.message = (
            f"expected {expected}, got {got.kind.name} {got.value!r}"
        )
        super().__init__(f"ParseError at {line}:{col}: {self.message}")


# Tokens that may end a statement-list inside a block or at top level.
_STMT_TERMINATORS_BLOCK = (TokenKind.RBRACE, TokenKind.EOF)


class Parser:
    """Recursive-descent parser over a token stream."""

    def __init__(self, tokens: list[Token]) -> None:
        self.tokens = tokens
        self.pos = 0

    # ── Cursor helpers ─────────────────────────────────────────────

    def peek(self, offset: int = 0) -> Token:
        idx = self.pos + offset
        if idx >= len(self.tokens):
            return self.tokens[-1]
        return self.tokens[idx]

    def advance(self) -> Token:
        tok = self.tokens[self.pos]
        if tok.kind is not TokenKind.EOF:
            self.pos += 1
        return tok

    def match(self, *kinds: TokenKind) -> Token | None:
        if self.peek().kind in kinds:
            return self.advance()
        return None

    def expect(self, kind: TokenKind, what: str | None = None) -> Token:
        tok = self.peek()
        if tok.kind is not kind:
            raise ParseError(tok.line, tok.col, what or kind.name, tok)
        return self.advance()

    # ── Entry point ────────────────────────────────────────────────

    def parse_script(self) -> Script:
        first = self.peek()
        stmts = self._parse_statements_until(_STMT_TERMINATORS_BLOCK)
        self.expect(TokenKind.EOF, "end of input")
        return Script(statements=tuple(stmts), line=first.line)

    # ── Statements ────────────────────────────────────────────────

    def _parse_statements_until(self, terminators: tuple[TokenKind, ...]) -> list[Stmt]:
        stmts: list[Stmt] = []
        while self.peek().kind not in terminators:
            stmts.append(self.parse_statement())
        return stmts

    def parse_statement(self) -> Stmt:
        tok = self.peek()
        kind = tok.kind

        if kind is TokenKind.LBRACE:
            return self.parse_block()
        if kind is TokenKind.KW_IF:
            return self.parse_if()
        if kind is TokenKind.KW_RETURN:
            return self._parse_terminator(ReturnStmt)
        if kind is TokenKind.KW_SKIP:
            return self._parse_terminator(SkipStmt)
        if kind is TokenKind.KW_ABORT:
            return self._parse_terminator(AbortStmt)

        # Expression statement, possibly an assignment.
        return self._parse_expr_or_assign_stmt()

    def parse_block(self) -> Block:
        lbrace = self.expect(TokenKind.LBRACE, "'{'")
        stmts = self._parse_statements_until((TokenKind.RBRACE, TokenKind.EOF))
        self.expect(TokenKind.RBRACE, "'}'")
        return Block(statements=tuple(stmts), line=lbrace.line)

    def parse_if(self) -> IfStmt:
        kw = self.expect(TokenKind.KW_IF, "'if'")
        self.expect(TokenKind.LPAREN, "'(' after 'if'")
        cond = self.parse_expression()
        self.expect(TokenKind.RPAREN, "')'")
        then_branch = self.parse_statement()
        else_branch: Stmt | None = None
        if self.match(TokenKind.KW_ELSE) is not None:
            else_branch = self.parse_statement()
        return IfStmt(cond=cond, then_branch=then_branch, else_branch=else_branch, line=kw.line)

    def _parse_terminator(self, cls):
        kw = self.advance()
        value: Expr | None = None
        if self.peek().kind is not TokenKind.SEMI:
            value = self.parse_expression()
        self.expect(TokenKind.SEMI, "';' after statement")
        return cls(value=value, line=kw.line)

    def _parse_expr_or_assign_stmt(self) -> Stmt:
        start_line = self.peek().line
        expr = self.parse_expression()
        assign = self.match(TokenKind.OP_ASSIGN, TokenKind.OP_COND_ASSIGN)
        if assign is not None:
            value = self.parse_expression()
            self.expect(TokenKind.SEMI, "';' after assignment")
            return AssignStmt(target=expr, op=assign.value, value=value, line=start_line)
        self.expect(TokenKind.SEMI, "';' after expression statement")
        return ExprStmt(expr=expr, line=start_line)

    # ── Expressions (precedence climbing) ─────────────────────────

    def parse_expression(self) -> Expr:
        return self._parse_or()

    def _parse_or(self) -> Expr:
        left = self._parse_and()
        while self.peek().kind is TokenKind.KW_OR:
            tok = self.advance()
            right = self._parse_and()
            left = BinaryOp(op="or", left=left, right=right, line=tok.line)
        return left

    def _parse_and(self) -> Expr:
        left = self._parse_comparison()
        while self.peek().kind is TokenKind.KW_AND:
            tok = self.advance()
            right = self._parse_comparison()
            left = BinaryOp(op="and", left=left, right=right, line=tok.line)
        return left

    _CMP_OPS = {
        TokenKind.OP_EQ: "=",
        TokenKind.OP_NEQ: "!=",
        TokenKind.OP_LT: "<",
        TokenKind.OP_LE: "<=",
        TokenKind.OP_GT: ">",
        TokenKind.OP_GE: ">=",
    }

    def _parse_comparison(self) -> Expr:
        left = self._parse_additive()
        while self.peek().kind in self._CMP_OPS:
            tok = self.advance()
            right = self._parse_additive()
            left = BinaryOp(op=self._CMP_OPS[tok.kind], left=left, right=right, line=tok.line)
        return left

    def _parse_additive(self) -> Expr:
        left = self._parse_multiplicative()
        while self.peek().kind in (TokenKind.OP_PLUS, TokenKind.OP_MINUS):
            tok = self.advance()
            op = "+" if tok.kind is TokenKind.OP_PLUS else "-"
            right = self._parse_multiplicative()
            left = BinaryOp(op=op, left=left, right=right, line=tok.line)
        return left

    def _parse_multiplicative(self) -> Expr:
        left = self._parse_unary()
        while self.peek().kind in (TokenKind.OP_STAR, TokenKind.OP_SLASH):
            tok = self.advance()
            op = "*" if tok.kind is TokenKind.OP_STAR else "/"
            right = self._parse_unary()
            left = BinaryOp(op=op, left=left, right=right, line=tok.line)
        return left

    def _parse_unary(self) -> Expr:
        if self.peek().kind is TokenKind.OP_MINUS:
            tok = self.advance()
            operand = self._parse_unary()
            return UnaryOp(op="-", operand=operand, line=tok.line)
        return self._parse_postfix()

    def _parse_postfix(self) -> Expr:
        expr = self._parse_primary()
        while True:
            tok = self.peek()
            if tok.kind is TokenKind.DOT:
                self.advance()
                name_tok = self.expect(TokenKind.IDENT, "field name after '.'")
                expr = FieldAccess(target=expr, field=name_tok.value, line=tok.line)
                continue
            if tok.kind is TokenKind.LPAREN:
                self.advance()
                args: list[Expr] = []
                if self.peek().kind is not TokenKind.RPAREN:
                    args.append(self.parse_expression())
                    while self.match(TokenKind.COMMA) is not None:
                        args.append(self.parse_expression())
                self.expect(TokenKind.RPAREN, "')' after call arguments")
                expr = Call(callee=expr, args=tuple(args), line=tok.line)
                continue
            break
        return expr

    def _parse_primary(self) -> Expr:
        tok = self.peek()
        kind = tok.kind

        if kind is TokenKind.NUMBER:
            self.advance()
            value = float(tok.value) if "." in tok.value else int(tok.value)
            return NumberLit(value=value, raw=tok.value, line=tok.line)
        if kind is TokenKind.STRING:
            self.advance()
            quote = '"'  # tokenizer drops the quote char; default to "
            return StringLit(value=tok.value, quote=quote, line=tok.line)
        if kind is TokenKind.IDENT:
            self.advance()
            return Identifier(name=tok.value, line=tok.line)
        if kind is TokenKind.LPAREN:
            self.advance()
            expr = self.parse_expression()
            self.expect(TokenKind.RPAREN, "')'")
            return expr

        raise ParseError(tok.line, tok.col, "expression", tok)
