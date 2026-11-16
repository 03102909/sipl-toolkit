from collections.abc import Iterator
from dataclasses import dataclass, fields
from typing import Any, ClassVar


@dataclass(frozen=True)
class SourceSpan:
    line: int
    column: int
    end_line: int
    end_column: int
    start_offset: int
    end_offset: int

    def merge(self, other: "SourceSpan") -> "SourceSpan":
        s = self if self.start_offset <= other.start_offset else other
        e = self if self.end_offset >= other.end_offset else other
        return SourceSpan(s.line, s.column, e.end_line, e.end_column, s.start_offset, e.end_offset)

    def extract(self, source: str) -> str:
        return source[self.start_offset : self.end_offset]

    def format_short(self) -> str:
        return f"L{self.line}:C{self.column}-L{self.end_line}:C{self.end_column}"

    def to_dict(self) -> dict[str, int]:
        return {f.name: getattr(self, f.name) for f in fields(self)}


@dataclass(frozen=True)
class Diagnostic:
    code: str
    severity: str
    message: str
    span: SourceSpan
    hint: str | None = None

    def format_human(self, source: str | None = None) -> str:
        parts = [f"[{self.code}] {self.severity} at line {self.span.line}:{self.span.column}: {self.message}"]
        lines = source.splitlines() if source is not None else []
        if 1 <= self.span.line <= len(lines):
            src = lines[self.span.line - 1]
            c, ec = self.span.column, self.span.end_column
            w = max(1, (ec - c) if self.span.line == self.span.end_line else (len(src) - c + 1))
            parts += [f"{self.span.line:>4} | {src}", f"     | {' ' * max(0, c - 1)}{'^' * w}"]
        if self.hint:
            parts.append(f"Hint: {self.hint}")
        return "\n".join(parts)

    def to_dict(self) -> dict[str, Any]:
        d = {"code": self.code, "severity": self.severity, "message": self.message, "span": self.span.to_dict()}
        return {**d, "hint": self.hint} if self.hint is not None else d


class SIPLDiagnosticError(Exception):
    def __init__(self, diagnostic: Diagnostic) -> None:
        self.diagnostic = diagnostic
        super().__init__(diagnostic.format_human())


class SIPLSyntaxError(SIPLDiagnosticError):
    pass


class SIPLRuntimeError(SIPLDiagnosticError):
    pass


@dataclass(frozen=True, kw_only=True)
class ASTNode:
    _RULE_PAIRS = (
        "Program:NP1 Assign:NS1 Seq:NS2 IfThenElse:NS3 WhileDo:NS4 Block:NS5 "
        "Skip:NS6 NumberLiteral:NA1 VariableRef:NA2 UnaryArithOp:NA_UNARY BoolNot:NB4"
    )
    RULE_IDS: ClassVar[dict[str, str]] = {k: v for k, v in (p.split(":") for p in _RULE_PAIRS.split())}
    span: SourceSpan
    node_id: str
    rule_id: str = ""

    def __post_init__(self) -> None:
        if not self.rule_id and self.kind in self.RULE_IDS:
            object.__setattr__(self, "rule_id", self.RULE_IDS[self.kind])

    @property
    def kind(self) -> str:
        return type(self).__name__

    def children_nodes(self) -> tuple["ASTNode", ...]:
        return tuple(getattr(self, f.name) for f in fields(self) if isinstance(getattr(self, f.name), ASTNode))

    def display_label(self) -> str:
        if isinstance(self, Assign):
            return f"Assign({self.var})"
        if isinstance(self, Seq):
            return "Seq"
        if isinstance(self, IfThenElse):
            return "If"
        if isinstance(self, WhileDo):
            return "While"
        if isinstance(self, NumberLiteral):
            return f"Num({self.value})"
        if isinstance(self, VariableRef):
            return f"Var({self.name})"
        if isinstance(self, (BinaryArithOp, UnaryArithOp, RelOp, BoolBinaryOp)):
            pfx = {"BinaryArithOp": "Op", "UnaryArithOp": "Unary", "RelOp": "Cond", "BoolBinaryOp": "Logic"}[self.kind]
            return f"{pfx}({self.op})"
        return "Not" if isinstance(self, BoolNot) else self.kind

    def walk(self) -> Iterator["ASTNode"]:
        yield self
        for child in self.children_nodes():
            yield from child.walk()

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"kind": self.kind, "span": self.span.format_short()}
        for f in fields(self):
            if f.name not in ("span", "node_id", "rule_id", "var_span"):
                val = getattr(self, f.name)
                out[f.name] = val.to_dict() if isinstance(val, ASTNode) else val
        return out


class Stmt(ASTNode):
    pass


class AExpr(ASTNode):
    pass


class BExpr(ASTNode):
    pass


@dataclass(frozen=True, kw_only=True)
class Program(ASTNode):
    body: Stmt


@dataclass(frozen=True, kw_only=True)
class Assign(Stmt):
    var: str
    var_span: SourceSpan
    expr: AExpr


@dataclass(frozen=True, kw_only=True)
class Seq(Stmt):
    first: Stmt
    second: Stmt


@dataclass(frozen=True, kw_only=True)
class IfThenElse(Stmt):
    condition: BExpr
    then_branch: Stmt
    else_branch: Stmt


@dataclass(frozen=True, kw_only=True)
class WhileDo(Stmt):
    condition: BExpr
    body: Stmt


@dataclass(frozen=True, kw_only=True)
class Block(Stmt):
    body: Stmt


@dataclass(frozen=True, kw_only=True)
class Skip(Stmt):
    pass


@dataclass(frozen=True, kw_only=True)
class NumberLiteral(AExpr):
    value: int


@dataclass(frozen=True, kw_only=True)
class VariableRef(AExpr):
    name: str


@dataclass(frozen=True, kw_only=True)
class BinaryArithOp(AExpr):
    op: str
    left: AExpr
    right: AExpr


@dataclass(frozen=True, kw_only=True)
class UnaryArithOp(AExpr):
    op: str
    operand: AExpr


@dataclass(frozen=True, kw_only=True)
class RelOp(BExpr):
    op: str
    left: AExpr
    right: AExpr


@dataclass(frozen=True, kw_only=True)
class BoolBinaryOp(BExpr):
    op: str
    left: BExpr
    right: BExpr


@dataclass(frozen=True, kw_only=True)
class BoolNot(BExpr):
    operand: BExpr


def format_expr(node: AExpr | BExpr) -> str:
    if isinstance(node, NumberLiteral):
        return str(node.value)
    if isinstance(node, VariableRef):
        return node.name
    if isinstance(node, UnaryArithOp):
        return f"-({format_expr(node.operand)})"
    if isinstance(node, (BinaryArithOp, BoolBinaryOp)):
        return f"({format_expr(node.left)} {node.op} {format_expr(node.right)})"
    if isinstance(node, RelOp):
        return f"{format_expr(node.left)} {node.op} {format_expr(node.right)}"
    return f"not ({format_expr(node.operand)})" if isinstance(node, BoolNot) else repr(node)
