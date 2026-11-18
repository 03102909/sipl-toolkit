from collections.abc import Iterator
from dataclasses import dataclass, fields
from typing import Any


@dataclass(frozen=True)
class SourceSpan:
    line: int
    column: int
    end_line: int
    end_column: int
    start_offset: int
    end_offset: int

    def merge(self, other: "SourceSpan") -> "SourceSpan":
        start = self if self.start_offset <= other.start_offset else other
        end = self if self.end_offset >= other.end_offset else other
        return SourceSpan(start.line, start.column, end.end_line, end.end_column, start.start_offset, end.end_offset)

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
        if source is not None:
            lines = source.splitlines()
            if 1 <= self.span.line <= len(lines):
                src_line = lines[self.span.line - 1]
                col = self.span.column
                if self.span.line == self.span.end_line:
                    width = max(1, self.span.end_column - col)
                else:
                    width = max(1, len(src_line) - col + 1)
                parts.append(f"{self.span.line:>4} | {src_line}")
                parts.append(f"     | {' ' * max(0, col - 1)}{'^' * width}")
        if self.hint:
            parts.append(f"Hint: {self.hint}")
        return "\n".join(parts)

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "span": self.span.to_dict(),
        }
        if self.hint is not None:
            data["hint"] = self.hint
        return data


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
    span: SourceSpan
    node_id: str
    rule_id: str = ""

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
        prefixes = {"BinaryArithOp": "Op", "UnaryArithOp": "Unary", "RelOp": "Cond", "BoolBinaryOp": "Logic"}
        if self.kind in prefixes:
            return f"{prefixes[self.kind]}({getattr(self, 'op')})"
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
    rule_id: str = "NP1"


@dataclass(frozen=True, kw_only=True)
class Assign(Stmt):
    var: str
    var_span: SourceSpan
    expr: AExpr
    rule_id: str = "NS1"


@dataclass(frozen=True, kw_only=True)
class Seq(Stmt):
    first: Stmt
    second: Stmt
    rule_id: str = "NS2"


@dataclass(frozen=True, kw_only=True)
class IfThenElse(Stmt):
    condition: BExpr
    then_branch: Stmt
    else_branch: Stmt
    rule_id: str = "NS3"


@dataclass(frozen=True, kw_only=True)
class WhileDo(Stmt):
    condition: BExpr
    body: Stmt
    rule_id: str = "NS4"


@dataclass(frozen=True, kw_only=True)
class Block(Stmt):
    body: Stmt
    rule_id: str = "NS5"


@dataclass(frozen=True, kw_only=True)
class Skip(Stmt):
    rule_id: str = "NS6"


@dataclass(frozen=True, kw_only=True)
class NumberLiteral(AExpr):
    value: int
    rule_id: str = "NA1"


@dataclass(frozen=True, kw_only=True)
class VariableRef(AExpr):
    name: str
    rule_id: str = "NA2"


@dataclass(frozen=True, kw_only=True)
class BinaryArithOp(AExpr):
    op: str
    left: AExpr
    right: AExpr


@dataclass(frozen=True, kw_only=True)
class UnaryArithOp(AExpr):
    op: str
    operand: AExpr
    rule_id: str = "NA_UNARY"


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
    rule_id: str = "NB4"


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
    if isinstance(node, BoolNot):
        return f"not ({format_expr(node.operand)})"
    return repr(node)
