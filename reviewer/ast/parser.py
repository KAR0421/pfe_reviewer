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
    ArrayIndex,
    AssignStmt,
    BinaryOp,
    Block,
    Call,
    DoWhile,
    Expr,
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
    Stmt,
    StringLit,
    TableSelector,
    TryStmt,
    UnaryOp,
    WhileStmt,
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

    def _peek_kw_ident(self, name: str, offset: int = 0) -> bool:
        """True if the token at ``offset`` is the contextual keyword ``name``.

        ``in``, ``to``, ``downto`` are not reserved (see ``tokens.py``);
        the parser recognises them by name where the grammar requires.
        """
        tok = self.peek(offset)
        return tok.kind is TokenKind.IDENT and tok.value.lower() == name

    def _expect_kw_ident(self, name: str, what: str) -> Token:
        if not self._peek_kw_ident(name):
            tok = self.peek()
            raise ParseError(tok.line, tok.col, what, tok)
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
        """Parse a single statement.

        Per the language spec, ``;`` is a *separator* between statements
        on the same line, not a terminator at end-of-line. The actual
        end-of-statement check lives in :meth:`_consume_stmt_end`.
        """
        tok = self.peek()
        kind = tok.kind

        if kind is TokenKind.LBRACE:
            return self.parse_block()
        if kind is TokenKind.KW_IF:
            return self.parse_if()
        if kind is TokenKind.KW_FOREACH:
            return self.parse_foreach()
        if kind is TokenKind.KW_FOR:
            return self.parse_for()
        if kind is TokenKind.KW_WHILE:
            return self.parse_while()
        if kind is TokenKind.KW_DO:
            return self.parse_do_while()
        if kind is TokenKind.KW_TRY:
            return self.parse_try()
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

    # ── Loops ──────────────────────────────────────────────────────

    def parse_foreach(self) -> Stmt:
        """``foreach X in Y do ...`` or ``foreach obj.TABLE do ...``.

        Disambiguated by the token after the first identifier: ``KW_IN``
        means list-form; ``DOT`` means table-form.
        """
        kw = self.expect(TokenKind.KW_FOREACH, "'foreach'")
        # Decide on the form by looking past the first ident.
        if self.peek().kind is TokenKind.IDENT and self._peek_kw_ident("in", 1):
            var_tok = self.advance()
            self._expect_kw_ident("in", "'in'")
            iterable = self.parse_expression()
            body = self._parse_loop_body()
            return ForeachList(
                var=Identifier(name=var_tok.value, line=var_tok.line),
                iterable=iterable,
                body=body,
                line=kw.line,
            )
        # Table form: parse a postfix expression (obj.TABLE possibly chained).
        target = self._parse_postfix()
        body = self._parse_loop_body()
        return ForeachTable(target=target, body=body, line=kw.line)

    def parse_for(self) -> Stmt:
        """``for (init; cond; step) ...`` or ``for X := n to/downto m do ...``.

        Disambiguated by whether the token after ``for`` is ``LPAREN`` or
        ``IDENT``.
        """
        kw = self.expect(TokenKind.KW_FOR, "'for'")
        if self.peek().kind is TokenKind.LPAREN:
            self.advance()  # consume '('
            # init: optional statement (assign or expr) terminated by ';'
            init: Stmt | None = None
            if self.peek().kind is not TokenKind.SEMI:
                init = self._parse_expr_or_assign_stmt()
            else:
                self.advance()  # consume the ';'
            # cond: optional expression terminated by ';'
            cond: Expr | None = None
            if self.peek().kind is not TokenKind.SEMI:
                cond = self.parse_expression()
            self.expect(TokenKind.SEMI, "';' after for-condition")
            # step: optional assign/expr without trailing ';'
            step: Stmt | None = None
            if self.peek().kind is not TokenKind.RPAREN:
                step = self._parse_for_step()
            self.expect(TokenKind.RPAREN, "')' after for-clauses")
            body = self.parse_statement()
            return ForCStyle(init=init, cond=cond, step=step, body=body, line=kw.line)

        # Counter form: for X := start to|downto end do ...
        var_tok = self.expect(TokenKind.IDENT, "loop variable")
        self.expect(TokenKind.OP_ASSIGN, "':=' in counted for")
        start = self.parse_expression()
        if self._peek_kw_ident("to"):
            direction = "to"
        elif self._peek_kw_ident("downto"):
            direction = "downto"
        else:
            tok = self.peek()
            raise ParseError(tok.line, tok.col, "'to' or 'downto'", tok)
        self.advance()
        end = self.parse_expression()
        body = self._parse_loop_body()
        return ForCounter(
            var=Identifier(name=var_tok.value, line=var_tok.line),
            start=start,
            direction=direction,
            end=end,
            body=body,
            line=kw.line,
        )

    def _parse_for_step(self) -> Stmt:
        """Parse a for-step (assignment or expression) without consuming ';'."""
        start_line = self.peek().line
        expr = self.parse_expression()
        assign = self.match(TokenKind.OP_ASSIGN, TokenKind.OP_COND_ASSIGN)
        if assign is not None:
            value = self.parse_expression()
            return AssignStmt(target=expr, op=assign.value, value=value, line=start_line)
        return ExprStmt(expr=expr, line=start_line)

    def _parse_loop_body(self) -> Stmt:
        """Parse a loop body, accepting either ``do <stmt>`` or a block.

        The grammar reference writes ``foreach X in Y do stmt`` and
        ``for X := a to b do stmt``, but real BizRule scripts routinely
        omit ``do`` when the body is a brace-delimited block:
        ``foreach a in list { ... }``. Both forms are accepted.
        """
        if self.match(TokenKind.KW_DO) is not None:
            return self.parse_statement()
        if self.peek().kind is TokenKind.LBRACE:
            return self.parse_block()
        tok = self.peek()
        raise ParseError(tok.line, tok.col, "'do' or '{' for loop body", tok)

    def parse_while(self) -> WhileStmt:
        kw = self.expect(TokenKind.KW_WHILE, "'while'")
        self.expect(TokenKind.LPAREN, "'(' after 'while'")
        cond = self.parse_expression()
        self.expect(TokenKind.RPAREN, "')'")
        body = self.parse_statement()
        return WhileStmt(cond=cond, body=body, line=kw.line)

    def parse_do_while(self) -> DoWhile:
        kw = self.expect(TokenKind.KW_DO, "'do'")
        body = self.parse_statement()
        self.expect(TokenKind.KW_WHILE, "'while' after do-body")
        self.expect(TokenKind.LPAREN, "'(' after 'while'")
        cond = self.parse_expression()
        self.expect(TokenKind.RPAREN, "')'")
        # Trailing `;` is optional at end-of-line, per the spec.
        self._consume_stmt_end()
        return DoWhile(body=body, cond=cond, line=kw.line)

    # ── try / onerror ──────────────────────────────────────────────

    def parse_try(self) -> TryStmt:
        kw = self.expect(TokenKind.KW_TRY, "'try'")
        try_block = self.parse_statement()
        # `onerror` must immediately follow the try-body.
        if self.peek().kind is not TokenKind.KW_ONERROR:
            tok = self.peek()
            raise ParseError(tok.line, tok.col, "'onerror' after try-body", tok)
        self.advance()
        onerror_block = self.parse_statement()
        return TryStmt(try_block=try_block, onerror_block=onerror_block, line=kw.line)

    def _parse_terminator(self, cls):
        kw = self.advance()
        value: Expr | None = None
        # A bare ``return`` / ``skip`` / ``abort`` (no value) is signalled
        # by the parser already being at a statement-end position.
        if not self._at_stmt_end():
            value = self.parse_expression()
        self._consume_stmt_end()
        return cls(value=value, line=kw.line)

    def _parse_expr_or_assign_stmt(self) -> Stmt:
        start_line = self.peek().line
        expr = self.parse_expression()
        assign = self.match(TokenKind.OP_ASSIGN, TokenKind.OP_COND_ASSIGN)
        if assign is not None:
            value = self.parse_expression()
            self._consume_stmt_end()
            return AssignStmt(target=expr, op=assign.value, value=value, line=start_line)
        self._consume_stmt_end()
        return ExprStmt(expr=expr, line=start_line)

    def _last_consumed_line(self) -> int:
        """Line of the most recently consumed token (1 if nothing yet)."""
        if self.pos == 0:
            return self.tokens[0].line if self.tokens else 1
        return self.tokens[self.pos - 1].line

    def _at_stmt_end(self) -> bool:
        """True if the parser is positioned at a statement boundary.

        A statement ends when the next token is one of:
        - ``;`` (explicit separator)
        - ``}`` or EOF (structural end of the enclosing block / script)
        - on a strictly later line than the last consumed token (newline
          acts as the natural separator)
        - ``else`` (structural follower of an if-then-branch)

        This is the *peek*-only version; :meth:`_consume_stmt_end` uses
        the same logic but additionally consumes a leading ``;``.
        """
        tok = self.peek()
        if tok.kind in (TokenKind.SEMI, TokenKind.RBRACE, TokenKind.EOF, TokenKind.KW_ELSE):
            return True
        return tok.line > self._last_consumed_line()

    def _consume_stmt_end(self) -> None:
        """Enforce the statement-separator rule and consume a leading ``;``.

        Per the language spec, ``;`` is a *separator* between statements,
        not a terminator at end-of-line:

        - ``x := 1`` (newline)         → valid
        - ``x := 1;``                  → valid
        - ``x := 1; y := 2``           → valid (``;`` separates them)
        - ``x := 1 y := 2``            → ParseError: ``;`` required between
          two statements on the same line.

        Implementation: an explicit ``;`` is consumed; otherwise the next
        token must already be at a statement boundary (different line, or
        ``}`` / EOF / ``else``). Anything else means the user wrote two
        statements on the same line without separating them.
        """
        if self.peek().kind is TokenKind.SEMI:
            self.advance()
            return
        tok = self.peek()
        if tok.kind in (TokenKind.RBRACE, TokenKind.EOF, TokenKind.KW_ELSE):
            return
        if tok.line > self._last_consumed_line():
            return
        raise ParseError(
            tok.line,
            tok.col,
            "';' between statements on the same line",
            tok,
        )

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
                # Look ahead for the `[ ... ]` row-selector form.
                if self.peek().kind is TokenKind.LBRACKET:
                    self.advance()
                    cond = self.parse_expression()
                    self.expect(TokenKind.RBRACKET, "']' after row selector")
                    expr = TableSelector(
                        target=expr, field=name_tok.value, condition=cond, line=tok.line
                    )
                else:
                    expr = FieldAccess(target=expr, field=name_tok.value, line=tok.line)
                continue
            if tok.kind is TokenKind.LBRACKET:
                # Array index `a[n]`.
                self.advance()
                index = self.parse_expression()
                self.expect(TokenKind.RBRACKET, "']' after array index")
                expr = ArrayIndex(array=expr, index=index, line=tok.line)
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
