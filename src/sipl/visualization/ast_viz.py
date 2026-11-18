from dataclasses import dataclass
from typing import Any

from sipl.ast import ASTNode, BExpr, Program, SourceSpan, Stmt


@dataclass
class VisualNode:
    node_id: str
    label: str
    span: SourceSpan
    children: tuple["VisualNode", ...] = ()
    subtitle: str | None = None
    is_leaf: bool = False
    leaf_index: int | None = None
    node_kind: str = "nonterminal"
    linked_id: str | None = None
    source_slice: str = ""


def dot_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def render_text_tree(root: VisualNode, show_spans: bool = False) -> str:
    lines: list[str] = []

    def visit(node: VisualNode, depth: int) -> None:
        parts = ([f"#{node.leaf_index}"] if node.leaf_index is not None else []) + [node.label]
        if show_spans:
            if node.subtitle:
                parts.append(f"[{node.subtitle}]")
            parts.append(f"@{node.span.format_short()}")
        lines.append(f"{'  ' * depth}{' '.join(parts)}")
        for child in node.children:
            visit(child, depth + 1)

    visit(root, 0)
    return "\n".join(lines)


def render_dot_tree(root: VisualNode, graph_name: str = "SIPLTree") -> str:
    lines = [f"digraph {graph_name} {{"]

    def visit(node: VisualNode) -> None:
        main = f"[{node.leaf_index}] {node.label}" if node.leaf_index is not None else node.label
        lbl = f"{main}\\n{node.subtitle}" if node.subtitle else main
        lines.append(f'  "{dot_escape(node.node_id)}" [label="{dot_escape(lbl)}"];')
        for child in node.children:
            lines.append(f'  "{dot_escape(node.node_id)}" -> "{dot_escape(child.node_id)}";')
            visit(child)

    visit(root)
    return "\n".join([*lines, "}"])


def ast_node_kind(node: ASTNode) -> str:
    if isinstance(node, Program):
        return "ast_prog"
    if isinstance(node, Stmt):
        return "ast_stmt"
    return "ast_cond" if isinstance(node, BExpr) else "ast_expr"


def ast_node_to_visual(node: ASTNode, source: str = "") -> VisualNode:
    sl = node.span.extract(source) if source else ""
    ch = tuple(ast_node_to_visual(child, source) for child in node.children_nodes())
    nk, lbl = ast_node_kind(node), node.display_label()
    return VisualNode(node.node_id, lbl, node.span, ch, node.rule_id, not ch, None, nk, node.node_id, sl)


def render_ast_text(ast: Program, source: str = "", show_spans: bool = False) -> str:
    return render_text_tree(ast_node_to_visual(ast, source), show_spans=show_spans)


def render_ast_json(ast: Program, source: str = "") -> dict[str, Any]:
    d: dict[str, Any] = {"kind": "AbstractSyntaxTree", "root": ast.to_dict()}
    return {**d, "source_length": len(source)} if source else d


def render_ast_dot(ast: Program, source: str = "") -> str:
    return render_dot_tree(ast_node_to_visual(ast, source), graph_name="SIPLAST")


def render_ast_svg(ast: Program, source: str = "") -> str:
    from sipl.visualization.parse_tree import render_svg_tree

    return render_svg_tree(ast_node_to_visual(ast, source), svg_id="ast-tree-svg", title="Abstract Syntax Tree (AST)")
