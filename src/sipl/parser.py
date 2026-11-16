from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from sipl import ast
from sipl.ast import Diagnostic, Program, SIPLSyntaxError
from sipl.lexer import ParseNode, Token, tokenize


def _ops(spec: str) -> dict[str, tuple[str, str]]:
    return {a: (b, c) for a, b, c in (p.split(":") for p in spec.split())}


MUL_OPS = _ops("STAR:*:NA5 DIV:div:NA7 SLASH:div:NA7 MOD:mod:NA8 PERCENT:mod:NA8")
ADD_OPS = _ops("PLUS:+:NA3 MINUS:-:NA4")
REL_OPS = _ops("EQ:=:NB1 GT:>:NB2 GE:>=:NB6 LT:<:NB7 LE:<=:NB8 NE:!=:NB9")
EXPR_FOLLOW = frozenset(MUL_OPS) | frozenset(ADD_OPS) | frozenset(REL_OPS)


def load_grammar() -> str:
    for path in (Path(__file__).resolve().parents[2] / "grammar" / "sipl.lark", Path.cwd() / "grammar" / "sipl.lark"):
        if path.is_file():
            return path.read_text(encoding="utf-8")
    raise FileNotFoundError("Grammar file grammar/sipl.lark not found")


@dataclass(frozen=True)
class ParseResult:
    source: str
    tokens: tuple[Token, ...]
    parse_tree: ParseNode
    ast: Program

    def to_dict(self, include_parse_tree: bool = True) -> dict[str, object]:
        d: dict[str, object] = {"ast": self.ast.to_dict()}
        return {**d, "parse_tree": self.parse_tree.to_dict()} if include_parse_tree else d


class Parser:
    def __init__(self, source: str, tokens: list[Token]) -> None:
        self.source, self.tokens, self.pos = source, tokens, 0
        self.seq = {"pt": 0, "ast": 0}

    def next_id(self, prefix: str) -> str:
        val = self.seq[prefix]
        self.seq[prefix] += 1
        return f"{prefix}_{val}"

    def cur(self) -> Token:
        return self.tokens[self.pos]

    def bump(self) -> Token:
        tok = self.tokens[self.pos]
        self.pos += 1
        return tok

    def tok_label(self, tok: Token) -> str:
        return "end of file" if tok.kind == "EOF" else repr(tok.lexeme)

    def err(self, code: str, msg: str, tok: Token | None = None, hint: str | None = None) -> SIPLSyntaxError:
        return SIPLSyntaxError(Diagnostic(code, "error", msg, (tok or self.cur()).span, hint))

    def consume(self, kind: str, msg: str, hint: str | None = None) -> Token:
        tok = self.cur()
        if tok.kind != kind:
            raise self.err("SYN001", f"{msg}, got {self.tok_label(tok)}", tok, hint)
        self.pos += 1
        return tok

    def nt(self, sym: str, cat: str, rule: str, items: list[Token | ParseNode], aid: str) -> ParseNode:
        ch = tuple(
            ParseNode(self.next_id("pt"), x.lexeme, "Terminal", None, x.span, (), x.lexeme, ast_node_id=aid)
            if isinstance(x, Token)
            else x
            for x in items
        )
        span = ch[0].span
        for c in ch[1:]:
            span = span.merge(c.span)
        return ParseNode(self.next_id("pt"), sym, cat, rule, span, ch, ast_node_id=aid)

    def make(
        self, sym: str, cat: str, rule: str, items: list[Token | ParseNode], cls: type[Any], **kw: Any
    ) -> tuple[ParseNode, Any]:
        aid = self.next_id("ast")
        pt = self.nt(sym, cat, rule, items, aid)
        return pt, cls(span=pt.span, node_id=aid, rule_id=rule, **kw)

    def number_leaves(self, root: ParseNode, counter: list[int] | None = None) -> ParseNode:
        cnt = counter if counter is not None else [1]
        if root.is_terminal:
            idx = cnt[0]
            cnt[0] += 1
            return replace(root, leaf_index=idx)
        return replace(root, children=tuple(self.number_leaves(c, cnt) for c in root.children))

    def bin_loop(
        self, sub: Callable[[], tuple[ParseNode, Any]], ops: dict[str, tuple[str, str]], cls: type[Any], s: str, c: str
    ) -> tuple[ParseNode, Any]:
        l_pt, l_ast = sub()
        while self.cur().kind in ops:
            op_tok, (r_pt, r_ast) = self.bump(), sub()
            op, rule = ops[op_tok.kind]
            l_pt, l_ast = self.make(s, c, rule, [l_pt, op_tok, r_pt], cls, op=op, left=l_ast, right=r_ast)
        return l_pt, l_ast

    def parse_program(self) -> tuple[ParseNode, Program]:
        if self.cur().kind == "EOF":
            raise self.err("SYN002", "Empty SIPL program; expected 'begin <statement> end'")
        b_tok = self.consume("KW_BEGIN", "Program must start with 'begin'")
        body_pt, body_ast = self.parse_stmt_seq()
        e_tok = self.consume("KW_END", "Expected 'end' to close program")
        if self.cur().kind != "EOF":
            raise self.err("SYN003", f"Unexpected token '{self.cur().lexeme}' after program 'end'")
        pt, root = self.make("<програма>", "Prog", "NP1", [b_tok, body_pt, e_tok], ast.Program, body=body_ast)
        return self.number_leaves(pt), root

    def parse_stmt_seq(self) -> tuple[ParseNode, ast.Stmt]:
        l_pt, l_ast = self.parse_stmt_atom()
        while self.cur().kind == "SEMI":
            s_tok = self.bump()
            if self.cur().kind in ("KW_END", "EOF", "KW_ELSE"):
                raise self.err("SYN004", f"Expected statement after ';' before '{self.cur().lexeme or 'EOF'}'", s_tok)
            r_pt, r_ast = self.parse_stmt_atom()
            l_pt, l_ast = self.make("<оператор>", "Stm", "NS2", [l_pt, s_tok, r_pt], ast.Seq, first=l_ast, second=r_ast)
        return l_pt, l_ast

    def make_num(self, tok: Token, value: int) -> tuple[ParseNode, ast.NumberLiteral]:
        aid = self.next_id("ast")
        pt = self.nt("<вираз>", "Aexp", "NA1", [self.nt("<число>", "Num", "NN", [tok], aid)], aid)
        return pt, ast.NumberLiteral(value=value, span=tok.span, node_id=aid)

    def parse_stmt_atom(self) -> tuple[ParseNode, ast.Stmt]:
        tok = self.cur()
        if tok.kind == "IDENT":
            self.pos += 1
            a_tok = self.consume("ASSIGN", f"Expected ':=' after variable '{tok.lexeme}'", "Use ':=' for assignment.")
            e_pt, e_ast = self.parse_aexp()
            aid = self.next_id("ast")
            v_pt = self.nt("<змінна>", "Var", "NV", [tok], aid)
            pt = self.nt("<оператор>", "Stm", "NS1", [v_pt, a_tok, e_pt], aid)
            return pt, ast.Assign(var=tok.lexeme, var_span=tok.span, expr=e_ast, span=pt.span, node_id=aid)
        if tok.kind == "KW_IF":
            self.pos += 1
            c_pt, c_ast = self.parse_bexp()
            t_tok = self.consume("KW_THEN", "Expected 'then' after 'if' condition")
            t_pt, t_ast = self.parse_stmt_atom()
            e_tok = self.consume("KW_ELSE", "Expected 'else' branch in 'if' statement")
            e_pt, e_ast = self.parse_stmt_atom()
            kw = {"condition": c_ast, "then_branch": t_ast, "else_branch": e_ast}
            return self.make("<оператор>", "Stm", "NS3", [tok, c_pt, t_tok, t_pt, e_tok, e_pt], ast.IfThenElse, **kw)
        if tok.kind == "KW_WHILE":
            self.pos += 1
            c_pt, c_ast = self.parse_bexp()
            d_tok = self.consume("KW_DO", "Expected 'do' after 'while' condition")
            b_pt, b_ast = self.parse_stmt_atom()
            items = [tok, c_pt, d_tok, b_pt]
            return self.make("<оператор>", "Stm", "NS4", items, ast.WhileDo, condition=c_ast, body=b_ast)
        if tok.kind == "KW_BEGIN":
            self.pos += 1
            b_pt, b_ast = self.parse_stmt_seq()
            e_tok = self.consume("KW_END", "Expected 'end' to close 'begin' block")
            return self.make("<оператор>", "Stm", "NS5", [tok, b_pt, e_tok], ast.Block, body=b_ast)
        if tok.kind == "KW_SKIP":
            return self.make("<оператор>", "Stm", "NS6", [self.bump()], ast.Skip)
        raise self.err("SYN005", f"Expected statement, got {self.tok_label(tok)}", tok)

    def parse_aexp(self) -> tuple[ParseNode, ast.AExpr]:
        def term() -> tuple[ParseNode, ast.AExpr]:
            return self.bin_loop(self.parse_afactor, MUL_OPS, ast.BinaryArithOp, "<вираз>", "Aexp")

        return self.bin_loop(term, ADD_OPS, ast.BinaryArithOp, "<вираз>", "Aexp")

    def parse_afactor(self) -> tuple[ParseNode, ast.AExpr]:
        tok = self.cur()
        if tok.kind == "MINUS":
            nxt = self.tokens[min(self.pos + 1, len(self.tokens) - 1)]
            if nxt.kind == "NUMBER" and tok.span.end_offset == nxt.span.start_offset:
                self.pos += 2
                neg = Token("NUMBER", tok.lexeme + nxt.lexeme, tok.lexeme + nxt.lexeme, tok.span.merge(nxt.span))
                return self.make_num(neg, -int(nxt.value))
            self.pos += 1
            op_pt, op_ast = self.parse_afactor()
            return self.make("<вираз>", "Aexp", "NA_UNARY", [tok, op_pt], ast.UnaryArithOp, op="-", operand=op_ast)
        if tok.kind == "LPAREN":
            self.pos += 1
            in_pt, in_ast = self.parse_aexp()
            rp = self.consume("RPAREN", "Expected ')' to close arithmetic expression")
            return self.nt("<вираз>", "Aexp", "NA6", [tok, in_pt, rp], in_ast.node_id), in_ast
        if tok.kind == "NUMBER":
            return self.make_num(self.bump(), int(tok.value))
        if tok.kind == "IDENT":
            self.pos += 1
            aid = self.next_id("ast")
            pt = self.nt("<вираз>", "Aexp", "NA2", [self.nt("<змінна>", "Var", "NV", [tok], aid)], aid)
            return pt, ast.VariableRef(name=tok.lexeme, span=tok.span, node_id=aid)
        raise self.err("SYN006", f"Expected arithmetic expression, got {self.tok_label(tok)}", tok)

    def parse_bexp(self) -> tuple[ParseNode, ast.BExpr]:
        def conj() -> tuple[ParseNode, ast.BExpr]:
            return self.bin_loop(self.parse_bnot, {"AND": ("and", "NB10")}, ast.BoolBinaryOp, "<умова>", "Bexp")

        return self.bin_loop(conj, {"OR": ("or", "NB3")}, ast.BoolBinaryOp, "<умова>", "Bexp")

    def parse_bnot(self) -> tuple[ParseNode, ast.BExpr]:
        if self.cur().kind == "NOT":
            tok = self.bump()
            in_pt, in_ast = self.parse_bnot()
            return self.make("<умова>", "Bexp", "NB4", [tok, in_pt], ast.BoolNot, operand=in_ast)
        return self.parse_batom()

    def parse_batom(self) -> tuple[ParseNode, ast.BExpr]:
        if self.cur().kind == "LPAREN":
            saved, lp = (self.pos, dict(self.seq)), self.bump()
            try:
                in_pt, in_ast = self.parse_bexp()
                rp = self.consume("RPAREN", "Expected ')' to close condition")
                if self.cur().kind not in EXPR_FOLLOW:
                    return self.nt("<умова>", "Bexp", "NB5", [lp, in_pt, rp], in_ast.node_id), in_ast
            except SIPLSyntaxError:
                pass
            self.pos, self.seq = saved
        l_pt, l_ast = self.parse_aexp()
        rel_tok = self.cur()
        if rel_tok.kind not in REL_OPS:
            msg = f"Expected relational operator in condition, got {self.tok_label(rel_tok)}"
            raise self.err("SYN007", msg, rel_tok)
        op, rule = REL_OPS[self.bump().kind]
        r_pt, r_ast = self.parse_aexp()
        return self.make("<умова>", "Bexp", rule, [l_pt, rel_tok, r_pt], ast.RelOp, op=op, left=l_ast, right=r_ast)


def parse_all(source: str) -> ParseResult:
    tokens = tokenize(source)
    pt, ast_root = Parser(source, tokens).parse_program()
    return ParseResult(source, tuple(tokens), pt, ast_root)


def parse(source: str) -> Program:
    return parse_all(source).ast
