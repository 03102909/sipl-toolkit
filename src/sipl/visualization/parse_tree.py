import html
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from sipl.lexer import ParseNode, Token
from sipl.visualization.ast_viz import VisualNode, render_dot_tree, render_text_tree


@dataclass
class LayoutBox:
    node: VisualNode
    width: float
    height: float
    subtree_width: float
    cx: float = 0.0
    cy: float = 0.0
    children: list["LayoutBox"] = field(default_factory=list)


def render_svg_tree(root: VisualNode, svg_id: str = "sipl-tree-svg", title: str = "") -> str:
    char_w, min_w, h_gap, level_gap = 7.4, 64.0, 18.0, 78.0
    mx, mtop, mbot = 28.0, (46.0 if title else 24.0), 32.0

    def measure(node: VisualNode) -> LayoutBox:
        bw = max(min_w, max(len(node.label), len(node.subtitle or "") + 2) * char_w + 22.0)
        bh = 40.0 if node.subtitle else 32.0
        cboxes = [measure(c) for c in node.children]
        cw = sum(cb.subtree_width for cb in cboxes) + h_gap * max(0, len(cboxes) - 1)
        return LayoutBox(node, bw, bh, max(bw, cw) if cboxes else bw, children=cboxes)

    max_y = mtop

    def assign(box: LayoutBox, lx: float, depth: int) -> None:
        nonlocal max_y
        box.cx, box.cy = lx + box.subtree_width / 2.0, mtop + depth * level_gap + box.height / 2.0
        max_y = max(max_y, box.cy + box.height / 2.0)
        cw = sum(cb.subtree_width for cb in box.children) + h_gap * max(0, len(box.children) - 1)
        cur = lx + (box.subtree_width - cw) / 2.0
        for cb in box.children:
            assign(cb, cur, depth + 1)
            cur += cb.subtree_width + h_gap

    rbox = measure(root)
    assign(rbox, mx, 0)
    tw, th = max(320.0, rbox.subtree_width + mx * 2.0), max_y + mbot
    mkr_id = f"arrow-{html.escape(svg_id)}"
    mkr = f'<marker id="{mkr_id}" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M 0 1 L 10 5 L 0 9 z"/></marker>'
    svg_open = f'<svg xmlns="http://www.w3.org/2000/svg" id="{html.escape(svg_id)}" viewBox="0 0 {tw:.1f} {th:.1f}" width="{tw:.1f}" height="{th:.1f}">'
    parts = [svg_open, f"<defs>{mkr}</defs>"]
    if title:
        parts.append(f'<text x="{tw / 2.0:.1f}" y="24" text-anchor="middle">{html.escape(title)}</text>')

    edges, nodes = [], []

    def emit(box: LayoutBox) -> None:
        n = box.node
        x0, y0 = box.cx - box.width / 2.0, box.cy - box.height / 2.0
        for cb in box.children:
            y1, y2 = box.cy + box.height / 2.0, cb.cy - cb.height / 2.0 - 2.0
            edges.append(
                f'<line x1="{box.cx:.1f}" y1="{y1:.1f}" x2="{cb.cx:.1f}" y2="{y2:.1f}" stroke="black" marker-end="url(#{mkr_id})"/>'
            )
        lbl = f"[{n.leaf_index}] {n.label}" if n.leaf_index is not None else n.label
        tip = f"{lbl}{f' [{n.subtitle}]' if n.subtitle else ''} @ {n.span.format_short()}"
        rect = f'<rect x="{x0:.1f}" y="{y0:.1f}" width="{box.width:.1f}" height="{box.height:.1f}" fill="white" stroke="black"/>'
        nodes.append(f"<g><title>{html.escape(tip)}</title>{rect}")
        if n.subtitle:
            t1 = f'<text x="{box.cx:.1f}" y="{y0 + 16:.1f}" text-anchor="middle">{html.escape(lbl)}</text>'
            t2 = f'<text x="{box.cx:.1f}" y="{y0 + 31:.1f}" text-anchor="middle">{html.escape(n.subtitle)}</text>'
            nodes.append(t1 + t2)
        else:
            nodes.append(f'<text x="{box.cx:.1f}" y="{box.cy + 4:.1f}" text-anchor="middle">{html.escape(lbl)}</text>')
        nodes.append("</g>")
        for cb in box.children:
            emit(cb)

    emit(rbox)
    return "\n".join(parts + edges + nodes + ["</svg>"])


@dataclass(frozen=True)
class YieldVerificationResult:
    matches: bool
    numbered_yield: str
    reconstructed_tokens: tuple[str, ...]
    expected_tokens: tuple[str, ...]
    leaf_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "matches": self.matches,
            "numbered_yield": self.numbered_yield,
            "reconstructed_tokens": list(self.reconstructed_tokens),
            "expected_tokens": list(self.expected_tokens),
            "leaf_count": self.leaf_count,
        }


def verify_parse_tree_yield(parse_tree: ParseNode, tokens: Sequence[Token] | None = None) -> YieldVerificationResult:
    leaves = parse_tree.leaves()
    rec = tuple(leaf.token_value if leaf.token_value is not None else leaf.symbol for leaf in leaves)
    num = " ".join(f"{lf.leaf_index or i} {tk}" for i, (lf, tk) in enumerate(zip(leaves, rec, strict=True), start=1))
    exp = rec if tokens is None else tuple(t.lexeme for t in tokens if t.kind != "EOF")
    return YieldVerificationResult(rec == exp, num, rec, exp, len(leaves))


def parse_node_to_visual(node: ParseNode, source: str = "") -> VisualNode:
    sl = node.span.extract(source) if source else (node.token_value or "")
    ch = tuple(parse_node_to_visual(c, source) for c in node.children)
    nk = "terminal" if node.is_terminal else "nonterminal"
    return VisualNode(
        node.id, node.symbol, node.span, ch, node.rule_id, node.is_terminal, node.leaf_index, nk, node.ast_node_id, sl
    )


def render_parse_tree_text(parse_tree: ParseNode, source: str = "", show_spans: bool = False) -> str:
    tree_str = render_text_tree(parse_node_to_visual(parse_tree, source), show_spans=show_spans)
    yr = verify_parse_tree_yield(parse_tree)
    return f"{tree_str}\n\nYield ({yr.leaf_count} terminals): {yr.numbered_yield}"


def render_parse_tree_json(
    parse_tree: ParseNode, source: str = "", tokens: Sequence[Token] | None = None
) -> dict[str, Any]:
    yr = verify_parse_tree_yield(parse_tree, tokens)
    return {
        "kind": "ConcreteParseTree",
        "yield_verification": {"matches": yr.matches, "leaf_count": yr.leaf_count, "numbered_yield": yr.numbered_yield},
        "root": parse_tree.to_dict(),
    }


def render_parse_tree_dot(parse_tree: ParseNode, source: str = "") -> str:
    return render_dot_tree(parse_node_to_visual(parse_tree, source), graph_name="SIPLParseTree")


def render_parse_tree_svg(parse_tree: ParseNode, source: str = "") -> str:
    return render_svg_tree(
        parse_node_to_visual(parse_tree, source), svg_id="parse-tree-svg", title="Concrete Parse Tree"
    )
