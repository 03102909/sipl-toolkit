import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from sipl.ast import Diagnostic, SIPLSyntaxError, SourceSpan

KEYWORDS = frozenset({"begin", "end", "if", "then", "else", "while", "do", "skip", "div", "mod", "or", "and", "not"})
_OP_SPEC = (
    ":=~ASSIGN~:= >=~GE~>= <=~LE~<= !=~NE~!= <>~NE~!= ==~EQ~= ||~OR~or &&~AND~and ;~SEMI~; "
    "(~LPAREN~( )~RPAREN~) +~PLUS~+ -~MINUS~- −~MINUS~- *~STAR~* ∗~STAR~* /~SLASH~div %~PERCENT~mod "
    "=~EQ~= >~GT~> <~LT~< ≥~GE~>= ≤~LE~<= ≠~NE~!= ∨~OR~or ∧~AND~and ¬~NOT~not !~NOT~not"
)
OP_MAP = {k: (t, v) for k, t, v in (item.split("~") for item in _OP_SPEC.split())}
KW_KINDS = {"or": "OR", "and": "AND", "not": "NOT", "div": "DIV", "mod": "MOD"}
TOKEN_RE = re.compile(
    r"(?P<NEWLINE>\n)|(?P<SKIP>[ \t\r]+|(?:#|//)[^\n]*)|(?P<BLOCK>/\*[\s\S]*?\*/)"
    r"|(?P<UNCLOSED>/\*[\s\S]*)|(?P<BAD_IDENT>[0-9]+[A-Za-z_][A-Za-z0-9_]*)"
    r"|(?P<NUMBER>[0-9]+)|(?P<IDENT>[A-Za-z_][A-Za-z0-9_]*)"
    r"|(?P<OP>:=|>=|<=|!=|<>|==|\|\||&&|[;()+*−∗/%=><≥≤≠∨∧¬!-])|(?P<MISMATCH>.)"
)


@dataclass(frozen=True)
class Token:
    kind: str
    lexeme: str
    value: str
    span: SourceSpan


@dataclass(frozen=True)
class ParseNode:
    id: str
    symbol: str
    category: str
    rule_id: str | None
    span: SourceSpan
    children: tuple["ParseNode", ...] = ()
    token_value: str | None = None
    leaf_index: int | None = None
    ast_node_id: str | None = None

    @property
    def is_terminal(self) -> bool:
        return self.category == "Terminal" and not self.children

    def walk(self) -> Iterator["ParseNode"]:
        yield self
        for child in self.children:
            yield from child.walk()

    def leaves(self) -> list["ParseNode"]:
        return [n for n in self.walk() if n.is_terminal]

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"symbol": self.symbol, "span": self.span.format_short()}
        if self.rule_id is not None:
            d["rule_id"] = self.rule_id
        if self.leaf_index is not None:
            d["leaf_index"] = self.leaf_index
        if self.children:
            d["children"] = [c.to_dict() for c in self.children]
        return d


def tokenize(source: str) -> list[Token]:
    tokens: list[Token] = []
    line, line_start = 1, 0
    for m in TOKEN_RE.finditer(source):
        kind, lex, start, end = m.lastgroup or "", m.group(), m.start(), m.end()
        sl, sc = line, start - line_start + 1
        if "\n" in lex:
            line += lex.count("\n")
            line_start = start + lex.rfind("\n") + 1
        span = SourceSpan(sl, sc, line, end - line_start + 1, start, end)
        if kind in ("NEWLINE", "SKIP", "BLOCK"):
            continue
        if kind in ("UNCLOSED", "BAD_IDENT", "MISMATCH"):
            msgs = {
                "UNCLOSED": ("LEX002", "Unterminated block comment '/*'"),
                "BAD_IDENT": ("LEX003", f"Invalid identifier starting with digit: '{lex}'"),
                "MISMATCH": ("LEX001", f"Unexpected character '{lex}'"),
            }
            code, msg = msgs[kind]
            raise SIPLSyntaxError(Diagnostic(code, "error", msg, span))
        if kind == "IDENT":
            tk = KW_KINDS.get(lex, f"KW_{lex.upper()}") if lex in KEYWORDS else "IDENT"
            tokens.append(Token(tk, lex, lex, span))
        elif kind == "NUMBER":
            tokens.append(Token("NUMBER", lex, lex, span))
        else:
            t_kind, val = OP_MAP[lex]
            tokens.append(Token(t_kind, lex, val, span))
    eof_col = len(source) - line_start + 1
    tokens.append(Token("EOF", "", "", SourceSpan(line, eof_col, line, eof_col, len(source), len(source))))
    return tokens
