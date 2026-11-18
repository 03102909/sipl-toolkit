from collections.abc import Iterator
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from lark import Lark, Tree, UnexpectedInput
from lark import Token as LarkToken

from sipl import ast
from sipl.ast import Diagnostic, Program, SIPLSyntaxError, SourceSpan

OP_NORM = {
    "−": "-",
    "∗": "*",
    "/": "div",
    "%": "mod",
    "==": "=",
    "≥": ">=",
    "≤": "<=",
    "≠": "!=",
    "<>": "!=",
    "∨": "or",
    "||": "or",
    "∧": "and",
    "&&": "and",
    "¬": "not",
    "!": "not",
}

RULE_META = {
    "np1_program": ("<програма>", "NP1"),
    "ns1_assign": ("<оператор>", "NS1"),
    "ns2_seq": ("<оператор>", "NS2"),
    "ns3_if": ("<оператор>", "NS3"),
    "ns4_while": ("<оператор>", "NS4"),
    "ns5_block": ("<оператор>", "NS5"),
    "ns6_skip": ("<оператор>", "NS6"),
    "na1_num": ("<вираз>", "NA1"),
    "na2_var": ("<вираз>", "NA2"),
    "na3_add": ("<вираз>", "NA3"),
    "na4_sub": ("<вираз>", "NA4"),
    "na5_mult": ("<вираз>", "NA5"),
    "na6_paren": ("<вираз>", "NA6"),
    "na7_div": ("<вираз>", "NA7"),
    "na8_mod": ("<вираз>", "NA8"),
    "na_unary_neg": ("<вираз>", "NA_UNARY"),
    "nb1_eq": ("<умова>", "NB1"),
    "nb2_gt": ("<умова>", "NB2"),
    "nb3_or": ("<умова>", "NB3"),
    "nb4_neg": ("<умова>", "NB4"),
    "nb5_paren": ("<умова>", "NB5"),
    "nb6_ge": ("<умова>", "NB6"),
    "nb7_lt": ("<умова>", "NB7"),
    "nb8_le": ("<умова>", "NB8"),
    "nb9_ne": ("<умова>", "NB9"),
    "nb10_and": ("<умова>", "NB10"),
}


def load_grammar() -> str:
    for path in (Path(__file__).resolve().parents[2] / "grammar" / "sipl.lark", Path.cwd() / "grammar" / "sipl.lark"):
        if path.is_file():
            return path.read_text(encoding="utf-8")
    raise FileNotFoundError("Grammar file grammar/sipl.lark not found")


_PARSER = Lark(load_grammar(), parser="lalr", propagate_positions=True, keep_all_tokens=True)


@dataclass(frozen=True)
class Token:
    kind: str
    lexeme: str
    span: SourceSpan


@dataclass(frozen=True)
class ParseNode:
    id: str
    symbol: str
    rule_id: str | None
    span: SourceSpan
    children: tuple["ParseNode", ...] = ()
    token_value: str | None = None
    leaf_index: int | None = None
    ast_node_id: str | None = None

    @property
    def is_terminal(self) -> bool:
        return not self.children

    def walk(self) -> Iterator["ParseNode"]:
        yield self
        for child in self.children:
            yield from child.walk()

    def leaves(self) -> list["ParseNode"]:
        return [n for n in self.walk() if n.is_terminal]

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"symbol": self.symbol, "span": self.span.format_short()}
        if self.rule_id is not None:
            data["rule_id"] = self.rule_id
        if self.leaf_index is not None:
            data["leaf_index"] = self.leaf_index
        if self.children:
            data["children"] = [c.to_dict() for c in self.children]
        return data


@dataclass(frozen=True)
class ParseResult:
    source: str
    tokens: tuple[Token, ...]
    parse_tree: ParseNode
    ast: Program

    def to_dict(self, include_parse_tree: bool = True) -> dict[str, object]:
        data: dict[str, object] = {"ast": self.ast.to_dict()}
        if include_parse_tree:
            data["parse_tree"] = self.parse_tree.to_dict()
        return data


def _tok_span(tok: LarkToken) -> SourceSpan:
    line = tok.line or 1
    col = tok.column or 1
    end_line = tok.end_line or line
    end_col = tok.end_column or (col + len(tok.value))
    start = tok.start_pos or 0
    end = tok.end_pos or (start + len(tok.value))
    return SourceSpan(line, col, end_line, end_col, start, end)


class _Builder:
    def __init__(self) -> None:
        self.pt_id = 0
        self.ast_id = 0

    def next_pt(self) -> str:
        self.pt_id += 1
        return f"pt_{self.pt_id - 1}"

    def next_ast(self) -> str:
        self.ast_id += 1
        return f"ast_{self.ast_id - 1}"

    def build(self, node: Tree[LarkToken] | LarkToken) -> tuple[ParseNode, Any]:
        if isinstance(node, LarkToken):
            pt = ParseNode(self.next_pt(), node.value, None, _tok_span(node), token_value=node.value)
            return pt, node

        rule_name = str(node.data)
        sym, rule_id = RULE_META[rule_name]
        built = [self.build(c) for c in node.children]
        pts = tuple(p for p, _ in built)
        vals = [v for _, v in built]
        span = pts[0].span
        for p in pts[1:]:
            span = span.merge(p.span)
        aid = self.next_ast()

        if rule_name == "np1_program":
            anode: Any = ast.Program(span=span, node_id=aid, body=vals[1])
        elif rule_name == "ns1_assign":
            anode = ast.Assign(span=span, node_id=aid, var=vals[0].value, var_span=pts[0].span, expr=vals[2])
        elif rule_name == "ns2_seq":
            anode = ast.Seq(span=span, node_id=aid, first=vals[0], second=vals[2])
        elif rule_name == "ns3_if":
            anode = ast.IfThenElse(span=span, node_id=aid, condition=vals[1], then_branch=vals[3], else_branch=vals[5])
        elif rule_name == "ns4_while":
            anode = ast.WhileDo(span=span, node_id=aid, condition=vals[1], body=vals[3])
        elif rule_name == "ns5_block":
            anode = ast.Block(span=span, node_id=aid, body=vals[1])
        elif rule_name == "ns6_skip":
            anode = ast.Skip(span=span, node_id=aid)
        elif rule_name == "na1_num":
            anode = ast.NumberLiteral(span=span, node_id=aid, value=int(vals[0].value))
        elif rule_name == "na2_var":
            anode = ast.VariableRef(span=span, node_id=aid, name=vals[0].value)
        elif rule_name == "na_unary_neg":
            if isinstance(vals[1], ast.NumberLiteral):
                anode = ast.NumberLiteral(span=span, node_id=vals[1].node_id, value=-vals[1].value)
            else:
                anode = ast.UnaryArithOp(span=span, node_id=aid, op="-", operand=vals[1])
        elif rule_name in ("na6_paren", "nb5_paren"):
            anode = vals[1]
        elif rule_name.startswith("na"):
            op = OP_NORM.get(vals[1].value, vals[1].value)
            anode = ast.BinaryArithOp(span=span, node_id=aid, rule_id=rule_id, op=op, left=vals[0], right=vals[2])
        elif rule_name in ("nb3_or", "nb10_and"):
            op = OP_NORM.get(vals[1].value, vals[1].value)
            anode = ast.BoolBinaryOp(span=span, node_id=aid, rule_id=rule_id, op=op, left=vals[0], right=vals[2])
        elif rule_name == "nb4_neg":
            anode = ast.BoolNot(span=span, node_id=aid, operand=vals[1])
        else:
            op = OP_NORM.get(vals[1].value, vals[1].value)
            anode = ast.RelOp(span=span, node_id=aid, rule_id=rule_id, op=op, left=vals[0], right=vals[2])

        linked = tuple(replace(p, ast_node_id=anode.node_id) if p.is_terminal else p for p in pts)
        return ParseNode(self.next_pt(), sym, rule_id, span, linked, ast_node_id=anode.node_id), anode


def _number_leaves(root: ParseNode, counter: list[int] | None = None) -> ParseNode:
    cnt = counter if counter is not None else [1]
    if root.is_terminal:
        idx = cnt[0]
        cnt[0] += 1
        return replace(root, leaf_index=idx)
    return replace(root, children=tuple(_number_leaves(c, cnt) for c in root.children))


def parse_all(source: str) -> ParseResult:
    try:
        tree = _PARSER.parse(source)
    except UnexpectedInput as exc:
        line = exc.line or 1
        col = exc.column or 1
        pos = exc.pos_in_stream or 0
        span = SourceSpan(line, col, line, col + 1, pos, min(len(source), pos + 1))
        raise SIPLSyntaxError(Diagnostic("SYN001", "error", str(exc).splitlines()[0], span)) from exc

    pt, ast_root = _Builder().build(tree)
    pt = _number_leaves(pt)
    tokens = tuple(Token(leaf.symbol, leaf.token_value or leaf.symbol, leaf.span) for leaf in pt.leaves())
    return ParseResult(source, tokens, pt, ast_root)


def parse(source: str) -> Program:
    return parse_all(source).ast
