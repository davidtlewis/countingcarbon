"""
Formula DSL — lexer, parser, AST, and evaluator.

Grammar:
    expr        := comparison
    comparison  := addition (('=' | '!=' | '<' | '<=' | '>' | '>=') addition)?
    addition    := term (('+' | '-') term)*
    term        := unary (('*' | '/') unary)*
    unary       := '-' unary | primary
    primary     := NUMBER | IDENT | call | '(' expr ')'
    call        := 'IF' '(' expr ',' expr ',' expr ')'
                 | 'MIN' '(' expr (',' expr)* ')'
                 | 'MAX' '(' expr (',' expr)* ')'
                 | 'ROUND' '(' expr ',' expr ')'
                 | 'LOOKUP' '(' STRING ',' expr ')'
                 | 'factor' '(' STRING ')'

All arithmetic is done in Decimal. Boolean results from comparisons are 0 or 1 (Decimal).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

# ── Limits ────────────────────────────────────────────────────────────────────

MAX_EXPRESSION_LENGTH = 1_000
MAX_AST_DEPTH = 20
MAX_EVAL_STEPS = 500

# ── Errors ────────────────────────────────────────────────────────────────────


class DSLSyntaxError(Exception):
    pass


class DSLEvalError(Exception):
    pass


# ── Tokens ────────────────────────────────────────────────────────────────────

TK_NUMBER = "NUMBER"
TK_STRING = "STRING"
TK_IDENT = "IDENT"
TK_PLUS = "+"
TK_MINUS = "-"
TK_STAR = "*"
TK_SLASH = "/"
TK_LPAREN = "("
TK_RPAREN = ")"
TK_COMMA = ","
TK_EQ = "="
TK_NEQ = "!="
TK_LT = "<"
TK_LTE = "<="
TK_GT = ">"
TK_GTE = ">="
TK_EOF = "EOF"

_TOKEN_RE = re.compile(
    r"""
    (?P<NUMBER>  \d+(?:\.\d*)?)        # integer or decimal
  | (?P<STRING>  "(?:[^"\\]|\\.)*")   # double-quoted string
  | (?P<IDENT>   [A-Za-z_][A-Za-z0-9_]*)
  | (?P<NEQ>     !=)
  | (?P<LTE>     <=)
  | (?P<GTE>     >=)
  | (?P<OP>      [+\-*/()=<>,])
  | (?P<WS>      \s+)
    """,
    re.VERBOSE,
)


@dataclass
class Token:
    kind: str
    value: str


def tokenise(expr: str) -> list[Token]:
    if len(expr) > MAX_EXPRESSION_LENGTH:
        raise DSLSyntaxError(
            f"Expression too long ({len(expr)} chars; limit {MAX_EXPRESSION_LENGTH})"
        )

    tokens: list[Token] = []
    pos = 0
    while pos < len(expr):
        m = _TOKEN_RE.match(expr, pos)
        if not m:
            raise DSLSyntaxError(
                f"Unexpected character at position {pos}: {expr[pos]!r}"
            )
        pos = m.end()
        if m.lastgroup == "WS":
            continue
        if m.lastgroup == "NUMBER":
            tokens.append(Token(TK_NUMBER, m.group()))
        elif m.lastgroup == "STRING":
            tokens.append(Token(TK_STRING, m.group()[1:-1]))  # strip quotes
        elif m.lastgroup == "IDENT":
            tokens.append(Token(TK_IDENT, m.group()))
        elif m.lastgroup == "NEQ":
            tokens.append(Token(TK_NEQ, "!="))
        elif m.lastgroup == "LTE":
            tokens.append(Token(TK_LTE, "<="))
        elif m.lastgroup == "GTE":
            tokens.append(Token(TK_GTE, ">="))
        elif m.lastgroup == "OP":
            ch = m.group()
            kind = {
                "+": TK_PLUS,
                "-": TK_MINUS,
                "*": TK_STAR,
                "/": TK_SLASH,
                "(": TK_LPAREN,
                ")": TK_RPAREN,
                ",": TK_COMMA,
                "=": TK_EQ,
                "<": TK_LT,
                ">": TK_GT,
            }[ch]
            tokens.append(Token(kind, ch))

    tokens.append(Token(TK_EOF, ""))
    return tokens


# ── AST nodes ─────────────────────────────────────────────────────────────────


@dataclass
class Number:
    value: Decimal


@dataclass
class Ident:
    name: str


@dataclass
class FactorRef:
    key: str


@dataclass
class BinOp:
    op: str
    left: Any
    right: Any


@dataclass
class UnaryMinus:
    operand: Any


@dataclass
class IfExpr:
    cond: Any
    then: Any
    else_: Any


@dataclass
class FuncCall:
    name: str  # MIN, MAX, ROUND
    args: list = field(default_factory=list)


@dataclass
class LookupCall:
    table: str
    value: Any


# ── Parser ────────────────────────────────────────────────────────────────────


class Parser:
    def __init__(self, tokens: list[Token]):
        self._tokens = tokens
        self._pos = 0
        self._depth = 0

    def _peek(self) -> Token:
        return self._tokens[self._pos]

    def _consume(self, kind: str | None = None) -> Token:
        tok = self._tokens[self._pos]
        if kind and tok.kind != kind:
            raise DSLSyntaxError(f"Expected {kind!r}, got {tok.kind!r} ({tok.value!r})")
        self._pos += 1
        return tok

    def _enter(self):
        self._depth += 1
        if self._depth > MAX_AST_DEPTH:
            raise DSLSyntaxError(
                f"Expression too deeply nested (limit {MAX_AST_DEPTH})"
            )

    def _exit(self):
        self._depth -= 1

    def parse(self):
        node = self._expr()
        self._consume(TK_EOF)
        return node

    def _expr(self):
        return self._comparison()

    def _comparison(self):
        self._enter()
        left = self._addition()
        tok = self._peek()
        if tok.kind in (TK_EQ, TK_NEQ, TK_LT, TK_LTE, TK_GT, TK_GTE):
            self._consume()
            right = self._addition()
            left = BinOp(tok.kind, left, right)
        self._exit()
        return left

    def _addition(self):
        self._enter()
        node = self._term()
        while self._peek().kind in (TK_PLUS, TK_MINUS):
            op = self._consume().kind
            node = BinOp(op, node, self._term())
        self._exit()
        return node

    def _term(self):
        self._enter()
        node = self._unary()
        while self._peek().kind in (TK_STAR, TK_SLASH):
            op = self._consume().kind
            node = BinOp(op, node, self._unary())
        self._exit()
        return node

    def _unary(self):
        if self._peek().kind == TK_MINUS:
            self._consume()
            return UnaryMinus(self._unary())
        return self._primary()

    def _primary(self):
        tok = self._peek()

        if tok.kind == TK_NUMBER:
            self._consume()
            try:
                return Number(Decimal(tok.value))
            except InvalidOperation:
                raise DSLSyntaxError(f"Invalid number: {tok.value!r}")

        if tok.kind == TK_LPAREN:
            self._consume(TK_LPAREN)
            node = self._expr()
            self._consume(TK_RPAREN)
            return node

        if tok.kind == TK_IDENT:
            name = tok.value
            # Peek ahead — if next is '(', it's a function call
            if self._tokens[self._pos + 1].kind == TK_LPAREN:
                return self._call(name)
            self._consume(TK_IDENT)
            return Ident(name)

        raise DSLSyntaxError(
            f"Unexpected token {tok.kind!r} ({tok.value!r}) at position {self._pos}"
        )

    def _call(self, name: str):
        self._consume(TK_IDENT)
        self._consume(TK_LPAREN)
        upper = name.upper()

        if upper == "IF":
            cond = self._expr()
            self._consume(TK_COMMA)
            then = self._expr()
            self._consume(TK_COMMA)
            else_ = self._expr()
            self._consume(TK_RPAREN)
            return IfExpr(cond, then, else_)

        if upper in ("MIN", "MAX"):
            args = [self._expr()]
            while self._peek().kind == TK_COMMA:
                self._consume(TK_COMMA)
                args.append(self._expr())
            self._consume(TK_RPAREN)
            return FuncCall(upper, args)

        if upper == "ROUND":
            x = self._expr()
            self._consume(TK_COMMA)
            places = self._expr()
            self._consume(TK_RPAREN)
            return FuncCall("ROUND", [x, places])

        if upper == "LOOKUP":
            table_tok = self._consume(TK_STRING)
            self._consume(TK_COMMA)
            val = self._expr()
            self._consume(TK_RPAREN)
            return LookupCall(table_tok.value, val)

        if name == "factor":
            key_tok = self._consume(TK_STRING)
            self._consume(TK_RPAREN)
            return FactorRef(key_tok.value)

        raise DSLSyntaxError(f"Unknown function: {name!r}")


def parse(expression: str):
    """Parse expression string to AST. Raises DSLSyntaxError on bad input."""
    tokens = tokenise(expression)
    return Parser(tokens).parse()


# ── Evaluator ─────────────────────────────────────────────────────────────────

_CMP_OPS = {
    TK_EQ: lambda a, b: Decimal(1) if a == b else Decimal(0),
    TK_NEQ: lambda a, b: Decimal(1) if a != b else Decimal(0),
    TK_LT: lambda a, b: Decimal(1) if a < b else Decimal(0),
    TK_LTE: lambda a, b: Decimal(1) if a <= b else Decimal(0),
    TK_GT: lambda a, b: Decimal(1) if a > b else Decimal(0),
    TK_GTE: lambda a, b: Decimal(1) if a >= b else Decimal(0),
}

_ARITH_OPS = {
    TK_PLUS: lambda a, b: a + b,
    TK_MINUS: lambda a, b: a - b,
    TK_STAR: lambda a, b: a * b,
}


def evaluate(
    node,
    context: dict,
    factors: dict,
    lookup_fn: Callable[[str, Decimal], Decimal] | None = None,
    _steps: list | None = None,
) -> Decimal:
    """
    Evaluate an AST node.

    Args:
        context: {field_name: Decimal} — validated input values
        factors: {factor_key: Decimal} — resolved factor values
        lookup_fn: callable(table_name, value) → Decimal for LOOKUP()
        _steps: mutable list used internally to count evaluation steps
    """
    if _steps is None:
        _steps = [0]
    _steps[0] += 1
    if _steps[0] > MAX_EVAL_STEPS:
        raise DSLEvalError(f"Evaluation exceeded step limit ({MAX_EVAL_STEPS})")

    if isinstance(node, Number):
        return node.value

    if isinstance(node, Ident):
        if node.name not in context:
            raise DSLEvalError(f"Unknown identifier: {node.name!r}")
        return Decimal(str(context[node.name]))

    if isinstance(node, FactorRef):
        if node.key not in factors:
            raise DSLEvalError(f"Factor not resolved: {node.key!r}")
        return Decimal(str(factors[node.key]))

    if isinstance(node, UnaryMinus):
        return -evaluate(node.operand, context, factors, lookup_fn, _steps)

    if isinstance(node, BinOp):
        left = evaluate(node.left, context, factors, lookup_fn, _steps)
        right = evaluate(node.right, context, factors, lookup_fn, _steps)
        if node.op in _CMP_OPS:
            return _CMP_OPS[node.op](left, right)
        if node.op in _ARITH_OPS:
            return _ARITH_OPS[node.op](left, right)
        if node.op == TK_SLASH:
            if right == 0:
                raise DSLEvalError("Division by zero")
            return left / right
        raise DSLEvalError(f"Unknown operator: {node.op!r}")

    if isinstance(node, IfExpr):
        cond = evaluate(node.cond, context, factors, lookup_fn, _steps)
        if cond != 0:
            return evaluate(node.then, context, factors, lookup_fn, _steps)
        return evaluate(node.else_, context, factors, lookup_fn, _steps)

    if isinstance(node, FuncCall):
        if node.name == "MIN":
            vals = [evaluate(a, context, factors, lookup_fn, _steps) for a in node.args]
            return min(vals)
        if node.name == "MAX":
            vals = [evaluate(a, context, factors, lookup_fn, _steps) for a in node.args]
            return max(vals)
        if node.name == "ROUND":
            x = evaluate(node.args[0], context, factors, lookup_fn, _steps)
            places = int(evaluate(node.args[1], context, factors, lookup_fn, _steps))
            quantiser = Decimal(10) ** -places
            return x.quantize(quantiser)
        raise DSLEvalError(f"Unknown function: {node.name!r}")

    if isinstance(node, LookupCall):
        if lookup_fn is None:
            raise DSLEvalError("LOOKUP() used but no lookup function provided")
        val = evaluate(node.value, context, factors, lookup_fn, _steps)
        return lookup_fn(node.table, val)

    raise DSLEvalError(f"Unknown AST node type: {type(node).__name__}")


def eval_expression(
    expression: str,
    context: dict,
    factors: dict,
    lookup_fn: Callable[[str, Decimal], Decimal] | None = None,
) -> Decimal:
    """Parse and evaluate an expression in one call. Returns a Decimal."""
    ast = parse(expression)
    return evaluate(ast, context, factors, lookup_fn)


def collect_factor_keys(node) -> set:
    """Walk an AST and return all factor() key references."""
    if isinstance(node, FactorRef):
        return {node.key}
    if isinstance(node, BinOp):
        return collect_factor_keys(node.left) | collect_factor_keys(node.right)
    if isinstance(node, UnaryMinus):
        return collect_factor_keys(node.operand)
    if isinstance(node, IfExpr):
        return (
            collect_factor_keys(node.cond)
            | collect_factor_keys(node.then)
            | collect_factor_keys(node.else_)
        )
    if isinstance(node, (FuncCall,)):
        result = set()
        for a in node.args:
            result |= collect_factor_keys(a)
        return result
    if isinstance(node, LookupCall):
        return collect_factor_keys(node.value)
    return set()


def collect_identifiers(node) -> set:
    """Walk an AST and return all Ident references (input field names)."""
    if isinstance(node, Ident):
        return {node.name}
    if isinstance(node, BinOp):
        return collect_identifiers(node.left) | collect_identifiers(node.right)
    if isinstance(node, UnaryMinus):
        return collect_identifiers(node.operand)
    if isinstance(node, IfExpr):
        return (
            collect_identifiers(node.cond)
            | collect_identifiers(node.then)
            | collect_identifiers(node.else_)
        )
    if isinstance(node, (FuncCall,)):
        result = set()
        for a in node.args:
            result |= collect_identifiers(a)
        return result
    if isinstance(node, LookupCall):
        return collect_identifiers(node.value)
    return set()
